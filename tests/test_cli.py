import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from inspect_ranges import __version__
from inspect_ranges._cli.main import ranges

EXAMPLE = str(
    Path(__file__).parent.parent
    / "src/inspect_ranges/examples/_vulhub_zabbix/range.yaml"
)


def test_version() -> None:
    result = CliRunner().invoke(ranges, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_accepts_example_and_rejects_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("range: {}\nunknown_section: 1\n")
    ok = CliRunner().invoke(ranges, ["validate", EXAMPLE])
    assert ok.exit_code == 0
    assert "vulhub-zabbix" in ok.output
    failed = CliRunner().invoke(ranges, ["validate", EXAMPLE, str(bad)])
    assert failed.exit_code == 1
    assert "unknown_section" in failed.output


def test_validate_unreadable_path_is_a_clean_error(tmp_path: Path) -> None:
    """A binary argument renders a positioned issue and the run keeps going per-file, no traceback."""
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xd8\x00\x00\x00")
    result = CliRunner().invoke(ranges, ["validate", str(binary), EXAMPLE])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_spec_verbs_accept_a_range_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory argument means its range.yaml (Journey A); one without range.yaml is a usage error."""
    monkeypatch.setenv("INSPECT_RANGES_BUILD_CACHE", str(tmp_path / "builds"))
    range_dir = Path(EXAMPLE).parent
    ok = CliRunner().invoke(ranges, ["validate", str(range_dir)])
    assert ok.exit_code == 0 and "vulhub-zabbix" in ok.output
    plan_result = CliRunner().invoke(ranges, ["plan", str(range_dir)])
    assert plan_result.exit_code == 1
    assert "declares guest content but" in plan_result.output  # the build-aware gate
    empty = CliRunner().invoke(ranges, ["validate", str(tmp_path)])
    assert empty.exit_code == 2 and "range.yaml" in empty.output


def test_validate_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "range.yaml").write_text(Path(EXAMPLE).read_text())
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(ranges, ["validate"])
    assert result.exit_code == 0 and "vulhub-zabbix" in result.output
    monkeypatch.chdir(tmp_path.parent)
    bare = CliRunner().invoke(ranges, ["validate"])
    assert bare.exit_code == 2 and "range.yaml" in bare.output


def test_validate_json_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("range: {}\nunknown_section: 1\n")
    result = CliRunner().invoke(ranges, ["validate", "--json", EXAMPLE, str(bad)])
    assert result.exit_code == 1
    reports = json.loads(result.output)
    # EXAMPLE's directory carries a challenges.yaml, reported as its own file
    assert [report["valid"] for report in reports] == [True, True, False]
    assert reports[1]["path"].endswith("challenges.yaml")
    issue = next(
        issue for issue in reports[2]["issues"] if issue["code"] == "unknown-key"
    )
    assert issue["path"] == "unknown_section"
    assert issue["line"] == 2


def test_validate_covers_sibling_challenges(tmp_path: Path) -> None:
    """A challenges.yaml beside the spec is validated too; without one, validate behaves exactly as before (one report)."""
    range_dir = Path(EXAMPLE).parent
    both = CliRunner().invoke(ranges, ["validate", str(range_dir)])
    assert both.exit_code == 0
    assert "vulhub-zabbix" in both.output and "challenges.yaml" in both.output
    (tmp_path / "range.yaml").write_text(Path(EXAMPLE).read_text())
    alone = CliRunner().invoke(ranges, ["validate", str(tmp_path)])
    assert alone.exit_code == 0 and "challenges.yaml" not in alone.output


def test_validate_cross_references_challenges_against_the_range(
    tmp_path: Path,
) -> None:
    """Sibling challenges validate against the range spec: a goal naming an undeclared host is a positioned error in the challenges report."""
    (tmp_path / "range.yaml").write_text(Path(EXAMPLE).read_text())
    (tmp_path / "challenges.yaml").write_text(
        "challenges:\n"
        "  - id: c\n"
        "    prompt: p\n"
        "    goals:\n"
        "      - { id: g, type: flag, host: nosuch, path: /f }\n"
    )
    result = CliRunner().invoke(ranges, ["validate", "--json", str(tmp_path)])
    assert result.exit_code == 1
    reports = json.loads(result.output)
    assert [report["valid"] for report in reports] == [True, False]
    issue = next(
        issue for issue in reports[1]["issues"] if issue["code"] == "unknown-goal-host"
    )
    assert issue["line"] is not None


def test_validate_refuses_unregistered_goal_type_with_known_names(
    tmp_path: Path,
) -> None:
    """The refusal posture matches the build: a custom type whose registration did not load reads unknown-goal-type with the known-name listing, never a misparse."""
    (tmp_path / "range.yaml").write_text(Path(EXAMPLE).read_text())
    (tmp_path / "challenges.yaml").write_text(
        "challenges:\n"
        "  - id: c\n"
        "    prompt: p\n"
        "    goals:\n"
        "      - { id: g, type: zzz }\n"
    )
    result = CliRunner().invoke(ranges, ["validate", "--json", str(tmp_path)])
    assert result.exit_code == 1
    reports = json.loads(result.output)
    issue = next(
        issue for issue in reports[1]["issues"] if issue["code"] == "unknown-goal-type"
    )
    assert "known types:" in issue["message"] and "flag" in issue["message"]


def test_plan_json_contract(tmp_path: Path) -> None:
    # a spec without guest content: migrated examples gate at planning by design
    spec = str(Path(__file__).parent.parent / "design/spikes/acl-v2/spec.yaml")
    result = CliRunner().invoke(ranges, ["plan", spec, "--json"])
    assert result.exit_code == 0
    plan = json.loads(result.output)
    assert plan["format_version"] == "1"
    assert plan["range"]["name"] == "acl-v2"
    assert plan["totals"]["guests"] == len(plan["guests"])


def test_plan_gates_migrated_guest_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The build-aware gate (slice 6): unbuilt content refuses range-not-built, pointing at build."""
    monkeypatch.setenv("INSPECT_RANGES_BUILD_CACHE", str(tmp_path / "builds"))
    result = CliRunner().invoke(ranges, ["plan", EXAMPLE])
    assert result.exit_code == 1
    assert "declares guest content but" in result.output
    assert "inspect-ranges build" in result.output


def test_render_writes_verifiable_bundle(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    spec = Path(__file__).parent.parent / "design/spikes/acl-v2/spec.yaml"
    (cache / "ubuntu-noble.qcow2").write_bytes(b"fake")
    (cache / "attack.qcow2").write_bytes(b"fake attack")
    out = tmp_path / "bundle"
    result = CliRunner().invoke(
        ranges,
        ["render", str(spec), "-o", str(out), "--image-cache", str(cache)],
    )
    assert result.exit_code == 0, result.output
    assert "bundle sha256:" in result.output
    manifest = json.loads((out / "manifest.json").read_text())
    assert "plan.json" in manifest["files"]


def test_plan_refuses_windows_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content-carrying Windows examples hit the build-aware gate first (the Windows-specific refusals — vmm, foothold, ip-required — are unit-covered in test_plan.py)."""
    monkeypatch.setenv("INSPECT_RANGES_BUILD_CACHE", str(tmp_path / "builds"))
    goad = str(
        Path(__file__).parent.parent
        / "src/inspect_ranges/examples/_goad_light/range.yaml"
    )
    result = CliRunner().invoke(ranges, ["plan", goad])
    assert result.exit_code == 1
    assert "declares guest content but" in result.output


def test_devbox_command_registered() -> None:
    result = CliRunner().invoke(ranges, ["devbox", "--help"])
    assert result.exit_code == 0
    assert "development box" in result.output


def test_schema_outputs_json() -> None:
    result = CliRunner().invoke(ranges, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.output)["properties"]["range"]


def test_doctor_fix_script_outputs_shell_script() -> None:
    # runs the real checks; the script shape holds whatever this machine's state
    result = CliRunner().invoke(ranges, ["doctor", "--fix-script"])
    assert result.exit_code == 0
    assert result.output.startswith("#!/bin/sh")


def test_doctor_fix_script_and_json_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(ranges, ["doctor", "--json", "--fix-script"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_doctor_json_exit_code_reflects_result() -> None:
    # runs the real checks, so assert only the output contract, not this machine's state
    result = CliRunner().invoke(ranges, ["doctor", "--json"])
    report = json.loads(result.output)
    assert result.exit_code == (0 if report["passed"] else 1)
    assert report["checks"]
    assert {check["status"] for check in report["checks"]} <= {
        "ok",
        "warn",
        "fail",
        "skip",
    }


def test_image_cache_knob_reaches_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`INSPECT_RANGES_IMAGE_CACHE` is the one cache default for every surface: the CLI must resolve through it, or the docs' claim ("images derive writes here") sends goldens to the wrong cache and doctor's printed fix reproduces the miss."""
    knob_cache = tmp_path / "knob-cache"
    knob_cache.mkdir()
    monkeypatch.setenv("INSPECT_RANGES_IMAGE_CACHE", str(knob_cache))
    result = CliRunner().invoke(ranges, ["images", "list"])
    assert result.exit_code == 0
    assert str(knob_cache) in result.output

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    overridden = CliRunner().invoke(
        ranges, ["images", "list", "--image-cache", str(explicit)]
    )
    assert overridden.exit_code == 0
    assert str(explicit) in overridden.output


def test_applier_startup_refusal_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unhealthy host's documented refusal surfaces as a one-line error with a nonzero exit, not a traceback (every other command converts expected failures the same way)."""
    from inspect_ranges._cli import appliercmd
    from inspect_ranges._host.local import HostNotReadyError

    class RefusingApplier:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def start(self) -> None:
            raise HostNotReadyError("host not ready: docker daemon (fail)")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(appliercmd, "Applier", RefusingApplier)
    result = CliRunner().invoke(
        ranges, ["applier", "--socket", str(tmp_path / "applier.sock")]
    )
    assert result.exit_code == 1
    assert "host not ready" in result.output
    assert "Traceback" not in result.output


def test_up_from_spec_leases_the_derived_project_and_failure_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no --cid-base, `up --from-spec` leases under the project `run_up` will derive (pinned into options so banner, teardown, and lease agree), a boot failure without --keep releases the block, and --keep holds it for `down`."""
    import inspect_ranges._cli.upcmd as upcmd_module
    from inspect_ranges._provider.naming import CidAllocator
    from inspect_ranges._runtime.up import UpError, UpResult

    state = tmp_path / "xdg" / "inspect-ranges" / "projects"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "img.qcow2").write_bytes(b"golden")
    spec_dir = tmp_path / "range"
    spec_dir.mkdir()
    (spec_dir / "range.yaml").write_text(
        """
range: { name: lease-check, schema_version: "0.3", description: cid lease test }
networks: [{ name: lab, cidr: 10.9.0.0/24, mode: isolated }]
hosts:
  - name: box
    os: { type: linux }
    image: img
    interfaces: [{ network: lab }]
attacker: { host: box, entry: external }
"""
    )
    seen: dict[str, object] = {}

    def fake_up(bundle: Path, options: object, **_: object) -> UpResult:
        seen["project"] = options.project
        if seen.get("fail"):
            raise UpError("guest-boot", "synthetic")
        return UpResult(
            project=str(options.project),
            range_name="lease-check",
            guests=[],
            seconds=0.1,
        )

    monkeypatch.setattr(upcmd_module, "run_up", fake_up)
    runner = CliRunner()
    args = [
        "up",
        "--from-spec",
        str(spec_dir / "range.yaml"),
        "--image-cache",
        str(cache),
    ]

    result = runner.invoke(ranges, args)
    assert result.exit_code == 0, result.output
    allocator = CidAllocator(state)
    leased_name = str(seen["project"])
    assert allocator.leased_projects(origin="cli") == [leased_name]
    allocator.release(leased_name)

    seen["fail"] = True
    result = runner.invoke(ranges, args)
    assert result.exit_code != 0
    assert allocator.leased_projects() == []  # un-kept failure released

    result = runner.invoke(ranges, [*args, "--keep"])
    assert result.exit_code != 0
    assert allocator.leased_projects(origin="cli") == [leased_name]  # kept range holds
