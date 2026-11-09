"""Capture semantics through the public seams, no VMs (round-1 review: the module had zero unit coverage and two of its defects would have been caught by exactly these tests)."""

import json
from pathlib import Path

import pytest
from inspect_ranges._build.capture import (
    RealizedImageMeta,
    capture_guest,
    wait_shutoff,
)
from inspect_ranges._build.errors import BuildError


def meta_for(golden: str) -> RealizedImageMeta:
    return RealizedImageMeta(
        range_name="caprange",
        guest="web",
        build_key="k" * 64,
        golden_file=golden,
        sha256="",
        created="2026-10-18T00:00:00Z",
    )


def fake_runner(cache: Path, payload: bytes) -> object:
    def runner(argv: list[str]) -> str:
        if argv[0] == "docker" and argv[1] == "cp":
            Path(argv[-1]).write_bytes(payload)
        return ""

    return runner


def test_capture_places_image_before_sidecar_and_cleans_temps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    # stale temps from a crashed prior capture of the SAME name are cleaned
    (cache / ".caprange-web-abc.qcow2.capturing").write_bytes(b"stale")
    placements: list[str] = []
    real_replace = Path.replace

    def tracking_replace(self: Path, target: "Path | str") -> Path:
        placements.append(str(target))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)
    digest = capture_guest(
        fake_runner(cache, b"overlay-bytes"),  # type: ignore[arg-type]
        "ir-cap-x",
        "web",
        image_cache=cache,
        golden_file="golden.qcow2",
        realized_name="caprange-web-abc.qcow2",
        meta=meta_for("golden.qcow2"),
    )
    monkeypatch.undo()
    image = cache / "caprange-web-abc.qcow2"
    sidecar = cache / "caprange-web-abc.realized.json"
    assert image.read_bytes() == b"overlay-bytes"
    recorded = json.loads(sidecar.read_text())
    assert recorded["sha256"] == digest
    # the image lands FIRST: a crash between placements never leaves a sidecar
    # describing a file that is not there (round-1)
    assert placements.index(str(image)) < placements.index(str(sidecar))
    assert not (cache / ".caprange-web-abc.qcow2.capturing").exists()


def test_capture_failure_leaves_no_temp_or_sidecar(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()

    def failing_runner(argv: list[str]) -> str:
        raise BuildError("capture", "docker cp exited 1: no such container")

    with pytest.raises(BuildError):
        capture_guest(
            failing_runner,  # type: ignore[arg-type]
            "ir-cap-x",
            "web",
            image_cache=cache,
            golden_file="golden.qcow2",
            realized_name="caprange-web-abc.qcow2",
            meta=meta_for("golden.qcow2"),
        )
    assert not (cache / "caprange-web-abc.qcow2").exists()
    assert not (cache / "caprange-web-abc.realized.json").exists()
    assert not (cache / ".caprange-web-abc.qcow2.capturing").exists()


def shutoff_runner(
    states: list[str],
    tail: str | None = None,
    calls: list[list[str]] | None = None,
) -> object:
    """A scripted CaptureRunner: `docker ps` resolves the range container, the VMM log tail returns `tail` (raising when None), and each state probe consumes `states` (the last repeats)."""
    remaining = list(states)

    def runner(argv: list[str]) -> str:
        if calls is not None:
            calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            return "rangecid\n"
        if "tail -n 5" in " ".join(argv):
            if tail is None:
                raise BuildError("capture", "docker exec exited 1: container gone")
            return tail
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return runner


def test_wait_shutoff_timeout_carries_the_shutdown_diagnosis() -> None:
    with pytest.raises(BuildError) as excinfo:
        wait_shutoff(
            shutoff_runner(["running"]),  # type: ignore[arg-type]
            "ir-cap-x",
            "web",
            timeout_s=0.1,
            shutdown_diagnosis="systemctl poweroff exited 1: bus error",
        )
    message = str(excinfo.value)
    assert "did not reach 'shut off'" in message
    assert "systemctl poweroff exited 1" in message


def test_wait_shutoff_resolves_the_range_service_by_label() -> None:
    """Capture and probe sidecars share the project label: the poll must exec the labeled range service, not a name-derived container."""
    calls: list[list[str]] = []
    wait_shutoff(
        shutoff_runner(["shut off"], calls=calls),  # type: ignore[arg-type]
        "ir-cap-x",
        "web",
        timeout_s=30.0,
    )
    listings = [call for call in calls if call[:2] == ["docker", "ps"]]
    execs = [call for call in calls if call[:2] == ["docker", "exec"]]
    assert listings and execs
    assert all(
        "label=com.docker.compose.service=range" in listed for listed in listings
    )
    assert all(call[2] == "rangecid" for call in execs)


def test_wait_shutoff_retries_a_transient_listing_failure() -> None:
    """A `docker ps` hiccup is a retried poll, never an abort: a false kill destroys a green build at its final step."""
    listings = {"count": 0}

    def runner(argv: list[str]) -> str:
        if argv[:2] == ["docker", "ps"]:
            listings["count"] += 1
            if listings["count"] == 1:
                raise BuildError("capture", "docker ps exited 1: daemon busy")
            return "rangecid\n"
        return "shut off"

    wait_shutoff(runner, "ir-cap-x", "web", timeout_s=30.0)  # type: ignore[arg-type]
    assert listings["count"] == 2


def test_wait_shutoff_refuses_when_no_range_container_runs() -> None:
    def no_containers(argv: list[str]) -> str:
        return "\n"

    with pytest.raises(BuildError) as excinfo:
        wait_shutoff(no_containers, "ir-cap-x", "web", timeout_s=0.1)  # type: ignore[arg-type]
    assert "no running range container" in str(excinfo.value)


def test_wait_shutoff_cloud_hypervisor_passes_the_guest_positionally() -> None:
    """The guest name rides as `$1`, never interpolated into the probe script, and a probe reporting shut off returns."""
    calls: list[list[str]] = []
    wait_shutoff(
        shutoff_runner(["shut off"], calls=calls),  # type: ignore[arg-type]
        "ir-cap-x",
        "web",
        timeout_s=30.0,
        cloud_hypervisor=True,
    )
    probe = calls[1]
    assert probe[3:5] == ["bash", "-c"]
    assert probe[-1] == "web" and "web" not in probe[5]


def test_wait_shutoff_cloud_hypervisor_timeout_folds_the_vmm_log_tail() -> None:
    """A missing pid cannot distinguish a clean poweroff from a VMM crash, so the timeout carries the VMM's own log tail beside the poweroff diagnosis."""
    with pytest.raises(BuildError) as excinfo:
        wait_shutoff(
            shutoff_runner(["running"], tail="Error booting VM\nvm exited\n"),  # type: ignore[arg-type]
            "ir-cap-x",
            "web",
            timeout_s=0.1,
            shutdown_diagnosis="poweroff exited 1",
            cloud_hypervisor=True,
        )
    message = str(excinfo.value)
    assert "did not reach 'shut off'" in message
    assert "poweroff exited 1" in message
    assert "vmm log: Error booting VM | vm exited" in message


def test_wait_shutoff_cloud_hypervisor_unreadable_log_keeps_the_timeout_error() -> None:
    """A failing tail must never mask the timeout: the error stands without the log line."""
    with pytest.raises(BuildError) as excinfo:
        wait_shutoff(
            shutoff_runner(["running"], tail=None),  # type: ignore[arg-type]
            "ir-cap-x",
            "web",
            timeout_s=0.1,
            cloud_hypervisor=True,
        )
    message = str(excinfo.value)
    assert "did not reach 'shut off'" in message
    assert "vmm log" not in message


def write_realized(cache: Path, range_name: str, guest: str, key: str) -> Path:
    image = cache / f"{range_name}-{guest}-{key}.qcow2"
    image.write_bytes(b"x" * 1024)
    sidecar = cache / f"{range_name}-{guest}-{key}.realized.json"
    sidecar.write_text(
        meta_for("golden.qcow2")
        .model_copy(
            update={"range_name": range_name, "guest": guest, "build_key": key * 6}
        )
        .model_dump_json()
    )
    return image


def test_collect_realized_garbage_is_range_scoped_and_keeps_the_kept(
    tmp_path: Path,
) -> None:
    """Parked-decisions item 1: the sweep deletes only this range's unkept generations; other ranges and unreadable sidecars are untouched."""
    from inspect_ranges._build.capture import collect_realized_garbage

    cache = tmp_path / "cache"
    cache.mkdir()
    current = write_realized(cache, "gcrange", "web", "aaaaaaaaaaaa")
    previous = write_realized(cache, "gcrange", "web", "bbbbbbbbbbbb")
    stale = write_realized(cache, "gcrange", "web", "cccccccccccc")
    other = write_realized(cache, "other", "web", "dddddddddddd")
    (cache / "broken-web-eeeeeeeeeeee.realized.json").write_text("{not json")
    deleted, reclaimed = collect_realized_garbage(
        "gcrange", cache, {current.name, previous.name}
    )
    assert deleted == 1 and reclaimed == 1024
    assert current.exists() and previous.exists() and other.exists()
    assert not stale.exists()
    assert not (cache / "gcrange-web-cccccccccccc.realized.json").exists()


def test_live_project_files_reads_boot_json(tmp_path: Path) -> None:
    import json

    from inspect_ranges._build.capture import live_project_files
    from inspect_ranges._runtime.ownership import owner_record, write_owner

    state = tmp_path / "state"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "boot.json").write_text(
        json.dumps(
            {
                "guests": [
                    {
                        "name": "web",
                        "image_file": "r-web-abc.qcow2",
                        "backing_file": "golden.qcow2",
                    }
                ]
            }
        )
    )
    write_owner(state, owner_record("ir-live-1", "r", "0" * 64, bundle))
    assert live_project_files(state) == {"r-web-abc.qcow2", "golden.qcow2"}


def test_windows_scrub_acl_guard_pins_the_lockdown_contract() -> None:
    r"""A tripwire over the guard's contract, not its spelling: no PowerShell runs in CI, so the live gates are the golden derive and the first Windows build, and this test exists to make an edit that narrows the contract a deliberate act.

    The contract: broad principals checked by SID (names vary by locale), the home and the binary refused all write-class access including the generic bits, work refused only ownership-class bits (its Modify grant is the deliberate exec-home exception), and the failure naming the re-derive remedy, because the common trip is a build on a pre-lockdown golden.
    """
    from inspect_ranges._build.capture import GUESTD_ACL_GUARD

    for sid in ("S-1-1-0", "S-1-5-11", "S-1-5-32-545"):
        assert sid in GUESTD_ACL_GUARD, sid
    # write-class plus GENERIC_WRITE and GENERIC_ALL for the home and binary;
    # ownership-class only for work
    assert "0x500D0156" in GUESTD_ACL_GUARD
    assert "0x100C0000" in GUESTD_ACL_GUARD
    for path, mask in (
        ("'C:\\guestd'", "$writeMask"),
        ("'C:\\guestd\\guestd.exe'", "$writeMask"),
        ("'C:\\guestd\\work'", "$ownMask"),
    ):
        assert f"@({path}, {mask})" in GUESTD_ACL_GUARD, path
    assert "derive-windows" in GUESTD_ACL_GUARD  # the remedy rides the error
