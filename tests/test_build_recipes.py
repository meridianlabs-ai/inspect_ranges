"""Recipe bundle resolution, digesting, vars validation, and the host-side executor, through the public `_build` surface with real fixture bundles and real subprocesses (no guest required)."""

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from inspect_ranges._build import (
    RecipeError,
    RecipeTarget,
    recipe_digest,
    resolve_recipe,
    run_recipe,
    validate_vars,
)
from inspect_ranges._build.guesttool import cids_from_env, exit_code
from inspect_ranges._channel.protocol import ExecRequest
from inspect_ranges._runtime.ownership import StageLog
from inspect_ranges.types import IssueError

TARGET = RecipeTarget(guest="web", cids={"web": 3100})


def write_recipe(
    root: Path,
    name: str = "acme.web",
    *,
    version: str = "1",
    entrypoint: str = "run.sh",
    mode: str = "online",
    inputs: dict[str, dict[str, Any]] | None = None,
    body: str = "#!/bin/sh\nexit 0\n",
    executable: bool = True,
) -> Path:
    """Materialize a recipe bundle under `root/recipes/<name>/` and return the bundle dir."""
    bundle = root / "recipes" / name
    bundle.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "name": name,
        "version": version,
        "entrypoint": entrypoint,
        "mode": mode,
    }
    if inputs is not None:
        manifest["inputs"] = inputs
    (bundle / "recipe.yaml").write_text(yaml.safe_dump(manifest))
    script = bundle / entrypoint
    script.write_text(body)
    if executable:
        script.chmod(0o755)
    return bundle


def codes(error: IssueError) -> list[str]:
    return [issue.code for issue in error.issues]


def test_resolve_from_range_dir(tmp_path: Path) -> None:
    write_recipe(tmp_path)
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    assert recipe.name == "acme.web"
    assert recipe.source == "range"
    assert recipe.entrypoint.is_file()


def test_range_dir_wins_over_cache(tmp_path: Path) -> None:
    write_recipe(tmp_path, version="2")
    staged = write_recipe(tmp_path / "staging", version="1")
    cache = tmp_path / "cache"
    cache.mkdir()
    staged.rename(cache / "acme.web")
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=cache)
    assert recipe.version == "2"
    assert recipe.source == "range"


def test_resolve_from_cache_when_range_lacks_it(tmp_path: Path) -> None:
    cache_home = tmp_path / "cachehome"
    bundle = write_recipe(cache_home, name="acme.db")
    cache = tmp_path / "cache"
    cache.mkdir()
    bundle.rename(cache / "acme.db")
    recipe = resolve_recipe("acme.db", range_dir=tmp_path, cache=cache)
    assert recipe.source == "cache"


def test_unresolved_recipe_is_a_coded_issue(tmp_path: Path) -> None:
    with pytest.raises(IssueError) as excinfo:
        resolve_recipe(
            "acme.missing",
            range_dir=tmp_path,
            cache=tmp_path / "cache",
            path=("hosts", 0, "provisioning", 1),
        )
    issue = excinfo.value.issues[0]
    assert issue.code == "recipe-not-resolved"
    assert issue.path == ("hosts", 0, "provisioning", 1)
    assert issue.hint is not None and "recipes/acme.missing" in issue.hint


def test_version_pin_mismatch(tmp_path: Path) -> None:
    write_recipe(tmp_path, version="2")
    with pytest.raises(IssueError) as excinfo:
        resolve_recipe(
            "acme.web", range_dir=tmp_path, cache=tmp_path / "cache", version="1"
        )
    assert codes(excinfo.value) == ["recipe-version-mismatch"]


def test_bundle_name_must_match_reference(tmp_path: Path) -> None:
    bundle = write_recipe(tmp_path, name="acme.web")
    bundle.rename(bundle.parent / "acme.other")
    with pytest.raises(IssueError) as excinfo:
        resolve_recipe("acme.other", range_dir=tmp_path, cache=tmp_path / "cache")
    assert codes(excinfo.value) == ["recipe-bundle-invalid"]


Mutator = Callable[[Path], object]

_MUTATORS: list[tuple[str, Mutator]] = [
    ("missing-yaml", lambda bundle: (bundle / "recipe.yaml").unlink()),
    (
        "broken-yaml",
        lambda bundle: (bundle / "recipe.yaml").write_text("name: [broken\n"),
    ),
    (
        "escaping-entrypoint",
        lambda bundle: (bundle / "recipe.yaml").write_text(
            yaml.safe_dump({"name": "acme.web", "version": "1", "entrypoint": "../x"})
        ),
    ),
    ("non-exec", lambda bundle: (bundle / "run.sh").chmod(0o644)),
    ("missing-entrypoint", lambda bundle: (bundle / "run.sh").unlink()),
]


@pytest.mark.parametrize(
    "mutate", [m for _, m in _MUTATORS], ids=[i for i, _ in _MUTATORS]
)
def test_invalid_bundles_refuse(tmp_path: Path, mutate: Mutator) -> None:
    bundle = write_recipe(tmp_path)
    mutate(bundle)
    with pytest.raises(IssueError) as excinfo:
        resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    assert codes(excinfo.value) == ["recipe-bundle-invalid"]


def test_digest_is_stable_across_identical_rebuilds(tmp_path: Path) -> None:
    first = write_recipe(tmp_path / "a", body="#!/bin/sh\necho hi\n")
    second = write_recipe(tmp_path / "b", body="#!/bin/sh\necho hi\n")
    assert recipe_digest(first) == recipe_digest(second)


def test_digest_changes_on_content_and_mode(tmp_path: Path) -> None:
    bundle = write_recipe(tmp_path, body="#!/bin/sh\necho hi\n")
    base = recipe_digest(bundle)
    (bundle / "extra.conf").write_text("x=1\n")
    with_file = recipe_digest(bundle)
    assert with_file != base
    (bundle / "extra.conf").chmod(0o755)
    assert recipe_digest(bundle) != with_file


def test_digest_refuses_symlinks(tmp_path: Path) -> None:
    bundle = write_recipe(tmp_path)
    (bundle / "link").symlink_to(bundle / "run.sh")
    with pytest.raises(IssueError) as excinfo:
        recipe_digest(bundle)
    assert codes(excinfo.value) == ["recipe-bundle-invalid"]


def test_vars_validate_and_render(tmp_path: Path) -> None:
    write_recipe(
        tmp_path,
        inputs={
            "db_host": {},
            "verbose": {"default": False},
            "port": {"default": 80},
        },
    )
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    env = validate_vars(recipe, {"db_host": "mysql", "verbose": True})
    assert env == {"db_host": "mysql", "verbose": "true", "port": "80"}


def test_vars_unknown_and_missing_collect_all(tmp_path: Path) -> None:
    write_recipe(tmp_path, inputs={"db_host": {}})
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    with pytest.raises(IssueError) as excinfo:
        validate_vars(recipe, {"bogus": "x"}, path=("hosts", 0, "provisioning", 0))
    assert sorted(codes(excinfo.value)) == ["recipe-var-missing", "recipe-var-unknown"]
    unknown = next(i for i in excinfo.value.issues if i.code == "recipe-var-unknown")
    assert unknown.path == ("hosts", 0, "provisioning", 0, "vars", "bogus")


def test_relative_range_dir_survives_the_executor_cwd_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_recipe(tmp_path / "range")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(tmp_path)
    recipe = resolve_recipe("acme.web", range_dir=Path("range"), cache=Path("cache"))
    assert recipe.bundle_dir.is_absolute() and recipe.entrypoint.is_absolute()
    monkeypatch.chdir(elsewhere)
    run = run_recipe(recipe, step_vars={}, target=TARGET, log_dir=tmp_path / "logs")
    assert run.log_path.is_file()


def test_run_recipe_success_exports_contract(tmp_path: Path) -> None:
    write_recipe(
        tmp_path,
        inputs={"db_host": {}},
        body=(
            "#!/bin/sh\n"
            'echo "db=$db_host guest=$IR_GUEST recipe=$IR_RECIPE" > "$PWD/out.txt"\n'
            'test -x "$IR_EXEC" && test -x "$IR_PUSH"\n'
        ),
    )
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    log = StageLog(tmp_path / "state", "ir-test")
    run = run_recipe(
        recipe,
        step_vars={"db_host": "mysql"},
        target=TARGET,
        log_dir=tmp_path / "logs",
        stage_log=log,
    )
    assert run.digest == recipe.digest
    assert run.log_path.is_file()
    assert (
        recipe.bundle_dir / "out.txt"
    ).read_text() == "db=mysql guest=web recipe=acme.web\n"
    events = log.events()
    assert [e["status"] for e in events] == ["start", "ok"]
    assert events[1]["guest"] == "web"


def test_run_recipe_nonzero_exit_names_everything(tmp_path: Path) -> None:
    write_recipe(tmp_path, body="#!/bin/sh\necho boom\nexit 3\n")
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    log = StageLog(tmp_path / "state", "ir-test")
    with pytest.raises(RecipeError) as excinfo:
        run_recipe(
            recipe,
            step_vars={},
            target=TARGET,
            log_dir=tmp_path / "logs",
            stage_log=log,
        )
    error = excinfo.value
    assert error.stage == "run"
    assert error.recipe == "acme.web" and error.guest == "web"
    assert "exited 3" in str(error) and "boom" in str(error)
    assert error.log_path.is_file() and "boom" in error.log_path.read_text()
    assert log.events()[-1]["status"] == "fail"


def test_run_recipe_budget_kills_the_process_group(tmp_path: Path) -> None:
    write_recipe(tmp_path, body="#!/bin/sh\nsleep 30 &\nsleep 30\n")
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    started = time.monotonic()
    with pytest.raises(RecipeError) as excinfo:
        run_recipe(
            recipe,
            step_vars={},
            target=TARGET,
            log_dir=tmp_path / "logs",
            budget_s=0.3,
        )
    assert excinfo.value.stage == "budget"
    assert time.monotonic() - started < 5.0
    assert "log:" in str(excinfo.value)


def test_offline_mode_is_a_typed_refusal(tmp_path: Path) -> None:
    write_recipe(tmp_path, mode="offline")
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    with pytest.raises(IssueError) as excinfo:
        run_recipe(recipe, step_vars={}, target=TARGET, log_dir=tmp_path / "logs")
    assert codes(excinfo.value) == ["recipe-mode-unsupported"]


@pytest.mark.parametrize("reference", ["/tmp/abs", "../escape", "a/b", "..", "UPPER"])
def test_traversal_shaped_references_refuse_before_any_join(
    tmp_path: Path, reference: str
) -> None:
    with pytest.raises(IssueError) as excinfo:
        resolve_recipe(reference, range_dir=tmp_path, cache=tmp_path / "cache")
    assert codes(excinfo.value) == ["recipe-reference-invalid"]


def test_launch_failure_is_a_staged_recipe_error(tmp_path: Path) -> None:
    # executable bit set but no shebang and binary junk: execve fails with ENOEXEC
    write_recipe(tmp_path, body="\x00\x01notascript")
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    log = StageLog(tmp_path / "state", "ir-test")
    with pytest.raises(RecipeError) as excinfo:
        run_recipe(
            recipe,
            step_vars={},
            target=TARGET,
            log_dir=tmp_path / "logs",
            stage_log=log,
        )
    assert excinfo.value.stage == "launch"
    assert excinfo.value.log_path.is_file()
    assert log.events()[-1]["status"] == "fail"


def test_zero_exit_survivors_are_swept(tmp_path: Path) -> None:
    write_recipe(
        tmp_path,
        body='#!/bin/sh\nsleep 30 >/dev/null 2>&1 </dev/null &\necho $! > "$PWD/childpid"\nexit 0\n',
    )
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    log = StageLog(tmp_path / "state", "ir-test")
    run_recipe(
        recipe, step_vars={}, target=TARGET, log_dir=tmp_path / "logs", stage_log=log
    )
    child = int((recipe.bundle_dir / "childpid").read_text())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"survivor {child} still alive after the sweep")
    assert log.events()[-1]["survivors_killed"] is True


def test_log_paths_are_per_run(tmp_path: Path) -> None:
    write_recipe(tmp_path)
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    first = run_recipe(recipe, step_vars={}, target=TARGET, log_dir=tmp_path / "logs")
    second = run_recipe(recipe, step_vars={}, target=TARGET, log_dir=tmp_path / "logs")
    assert first.log_path != second.log_path
    assert first.log_path.is_file() and second.log_path.is_file()


def test_guesttool_contract_parsing() -> None:
    guest, cids = cids_from_env(
        {"IR_GUEST": "web", "IR_GUEST_CIDS": '{"web": 3100, "db": 3101}'}
    )
    assert guest == "web" and cids == {"web": 3100, "db": 3101}
    with pytest.raises(ValueError):
        cids_from_env({"IR_GUEST": "web", "IR_GUEST_CIDS": '{"db": 3101}'})
    with pytest.raises(ValueError):
        cids_from_env({})
    with pytest.raises(ValueError):
        cids_from_env({"IR_GUEST": "web", "IR_GUEST_CIDS": "not json"})


def test_guesttool_exit_codes() -> None:
    assert exit_code(0) == 0
    assert exit_code(7) == 7
    assert exit_code(-9) == 137


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("msg", "a\x00b"),
        ("a=b", "x"),
        ("", "x"),
    ],
)
def test_vars_that_cannot_cross_the_environment_refuse(
    tmp_path: Path, key: str, value: str
) -> None:
    """Round-1 blocking: a NUL or '=' slipping into Popen's env raised a raw ValueError mid-build, past teardown."""
    write_recipe(tmp_path, name="acme.env", inputs={key: {}} if key else {})
    recipe = resolve_recipe("acme.env", range_dir=tmp_path, cache=tmp_path / "nocache")
    with pytest.raises(IssueError) as excinfo:
        validate_vars(recipe, {key: value})
    assert any(
        issue.code in ("recipe-var-invalid", "recipe-var-unknown")
        for issue in excinfo.value.issues
    )
    assert any(issue.code == "recipe-var-invalid" for issue in excinfo.value.issues)


def test_default_with_nul_refuses(tmp_path: Path) -> None:
    write_recipe(tmp_path, name="acme.dflt", inputs={"msg": {"default": "a\x00b"}})
    recipe = resolve_recipe("acme.dflt", range_dir=tmp_path, cache=tmp_path / "nocache")
    with pytest.raises(IssueError) as excinfo:
        validate_vars(recipe, {})
    assert excinfo.value.issues[0].code == "recipe-var-invalid"


def test_guest_os_contract_parsing() -> None:
    from inspect_ranges._build.guesttool import guest_os_from_env

    assert guest_os_from_env({}) == {}
    assert guest_os_from_env({"IR_GUEST_OS": '{"dc": "windows", "web": "linux"}'}) == {
        "dc": "windows",
        "web": "linux",
    }
    with pytest.raises(ValueError):
        guest_os_from_env({"IR_GUEST_OS": "not json"})
    with pytest.raises(ValueError):
        guest_os_from_env({"IR_GUEST_OS": '{"dc": 1}'})


def test_contract_env_exports_guest_os(tmp_path: Path) -> None:
    """The executor serializes the per-guest OS map so `IR_EXEC`/`IR_PUSH` pick the Windows shapes against Windows targets."""
    write_recipe(tmp_path, body='#!/bin/sh\necho "$IR_GUEST_OS" > "$PWD/os.txt"\n')
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    run_recipe(
        recipe,
        step_vars={},
        target=RecipeTarget(
            guest="web", cids={"web": 3100}, guest_os={"web": "windows"}
        ),
        log_dir=tmp_path / "logs",
    )
    assert (recipe.bundle_dir / "os.txt").read_text().strip() == '{"web": "windows"}'


def test_contract_env_exports_ad_and_defense(tmp_path: Path) -> None:
    """The executor serializes IR_ACTIVE_DIRECTORY and the target host's IR_HOST_DEFENSE only when declared (windows-ad-v1 slice 4): the spec is the single source the domain recipes realize from."""
    write_recipe(
        tmp_path,
        body='#!/bin/sh\nprintf "%s|%s" "${IR_ACTIVE_DIRECTORY:-absent}" "${IR_HOST_DEFENSE:-absent}" > "$PWD/contract.txt"\n',
    )
    recipe = resolve_recipe("acme.web", range_dir=tmp_path, cache=tmp_path / "cache")
    run_recipe(
        recipe,
        step_vars={},
        target=RecipeTarget(
            guest="web",
            cids={"web": 3100},
            active_directory='{"forest": "corp.local"}',
            host_defense='{"defender": false}',
        ),
        log_dir=tmp_path / "logs",
    )
    assert (recipe.bundle_dir / "contract.txt").read_text() == (
        '{"forest": "corp.local"}|{"defender": false}'
    )
    run_recipe(
        recipe,
        step_vars={},
        target=RecipeTarget(guest="web", cids={"web": 3100}),
        log_dir=tmp_path / "logs",
    )
    assert (recipe.bundle_dir / "contract.txt").read_text() == "absent|absent"


class _FakePushChannel:
    """Records write_file/exec calls for the push seam; always succeeds."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, int, int | None]] = []
        self.commands: list[list[str]] = []
        self.exec_rc = 0

    async def write_file(
        self, guest: str, path: str, data: bytes, *, mode: int | None = None
    ) -> int:
        self.writes.append((guest, path, len(data), mode))
        return 1

    async def exec(self, guest: str, request: "ExecRequest") -> object:
        from types import SimpleNamespace

        self.commands.append(list(request.cmd))
        return SimpleNamespace(rc=self.exec_rc, stdout=b"", stderr=b"promote failed")


def _push_env(monkeypatch: pytest.MonkeyPatch, os_name: str = "linux") -> None:
    monkeypatch.setenv("IR_GUEST", "box")
    monkeypatch.setenv("IR_GUEST_CIDS", '{"box": 3}')
    monkeypatch.setenv("IR_GUEST_OS", f'{{"box": "{os_name}"}}')


def test_push_streams_large_files_in_chunks_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file over the chunk size streams as ordered sub-cap chunks and the promote reassembles, sha-verifies, installs, and sweeps staging; a small file keeps the single-write path with no reassembly."""
    import hashlib

    import inspect_ranges._build.guesttool as guesttool_module
    from inspect_ranges._build.guesttool import main

    _push_env(monkeypatch)
    channel = _FakePushChannel()

    def fake_channel(*args: object, **kwargs: object) -> _FakePushChannel:
        return channel

    monkeypatch.setattr(guesttool_module, "MessageChannel", fake_channel)
    monkeypatch.setattr(guesttool_module, "PUSH_CHUNK_BYTES", 1024)

    big = tmp_path / "big.bin"
    payload = bytes(range(256)) * 12  # 3072 bytes = 3 chunks
    big.write_bytes(payload)
    assert main(["push", str(big), "/opt/dest.bin", "--mode", "644"]) == 0
    assert [w[2] for w in channel.writes] == [1024, 1024, 1024]
    suffixes = [w[1].rsplit(".", 1)[-1] for w in channel.writes]
    assert suffixes == [f"{i:04d}" for i in range(3)]  # zero-padded write order
    promote = channel.commands[-1][-1]
    assert hashlib.sha256(payload).hexdigest() in promote
    assert "sha256sum -c" in promote and "install -D -m 644" in promote

    channel.writes.clear()
    channel.commands.clear()
    small = tmp_path / "small.bin"
    small.write_bytes(b"tiny")
    assert main(["push", str(small), "/opt/small.bin", "--mode", "644"]) == 0
    assert len(channel.writes) == 1
    assert "sha256sum" not in channel.commands[-1][-1]


def test_push_chunked_windows_promote_reassembles_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows promote concatenates the ordered parts, compares Get-FileHash against the source digest, and only then moves to the destination."""
    import hashlib

    import inspect_ranges._build.guesttool as guesttool_module
    from inspect_ranges._build.guesttool import main

    _push_env(monkeypatch, os_name="windows")
    channel = _FakePushChannel()

    def fake_channel(*args: object, **kwargs: object) -> _FakePushChannel:
        return channel

    monkeypatch.setattr(guesttool_module, "MessageChannel", fake_channel)
    monkeypatch.setattr(guesttool_module, "PUSH_CHUNK_BYTES", 512)
    big = tmp_path / "big.iso"
    payload = b"\x7f" * 1300  # 3 chunks
    big.write_bytes(payload)
    assert main(["push", str(big), "C:\\dest\\big.iso"]) == 0
    assert len(channel.writes) == 3
    promote = channel.commands[-1][-1]
    assert hashlib.sha256(payload).hexdigest() in promote
    assert "Get-FileHash" in promote and "Move-Item" in promote


def test_push_chunk_size_fits_the_daemon_cap() -> None:
    """The chunk size derives from the inbound cap, so a cap change can never strand pushes mid-stream."""
    from inspect_ranges._build.guesttool import PUSH_CHUNK_BYTES
    from inspect_ranges._channel.protocol import DAEMON_INBOUND_BULK_CAP

    assert 0 < PUSH_CHUNK_BYTES <= DAEMON_INBOUND_BULK_CAP


def test_push_promote_failure_passes_the_exit_status_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing promote surfaces its in-guest exit status (and stderr) instead of a silent zero."""
    import inspect_ranges._build.guesttool as guesttool_module
    from inspect_ranges._build.guesttool import main

    _push_env(monkeypatch)
    channel = _FakePushChannel()
    channel.exec_rc = 1

    def fake_channel(*args: object, **kwargs: object) -> _FakePushChannel:
        return channel

    monkeypatch.setattr(guesttool_module, "MessageChannel", fake_channel)
    small = tmp_path / "s.bin"
    small.write_bytes(b"x")
    assert main(["push", str(small), "/opt/s.bin", "--mode", "644"]) == 1
