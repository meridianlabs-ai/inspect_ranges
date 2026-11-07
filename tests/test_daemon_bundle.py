"""Slice 5 battery: the daemon bundle is byte-deterministic and tamper-refusing.

Skips without a Go toolchain (same policy as `test_go_daemon.py`): CI provides the pin, so determinism is enforced there, never silently skipped.
"""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from inspect_ranges._channel.bundle import (
    BundleError,
    DaemonBundleInfo,
    build_daemon_bundle,
    bundle_file_name,
    verify_daemon_bundle,
)
from inspect_ranges._cli.main import ranges

from tests.test_go_daemon import REQUIRE_GO, go_binary

pytestmark = pytest.mark.skipif(
    go_binary is None and not REQUIRE_GO,
    reason="no Go toolchain (see daemon/linux/README.md for the pin)",
)


def test_bundle_builds_twice_byte_identical(tmp_path: Path) -> None:
    first = build_daemon_bundle(tmp_path / "a")
    second = build_daemon_bundle(tmp_path / "b")
    assert first.bundle_sha256 == second.bundle_sha256, (
        "the bundle is not deterministic"
    )
    blob_a = (tmp_path / "a" / bundle_file_name()).read_bytes()
    blob_b = (tmp_path / "b" / bundle_file_name()).read_bytes()
    assert blob_a == blob_b


def test_bundle_verifies_and_refuses_tamper(tmp_path: Path) -> None:
    info = build_daemon_bundle(tmp_path)
    bundle_path = tmp_path / bundle_file_name()
    verify_daemon_bundle(bundle_path, info)

    # tamper one member, repack, keep the sidecar: member digests must refuse
    with tarfile.open(bundle_path, "r:") as tar:
        members = {
            member.name: tar.extractfile(member).read()  # type: ignore[union-attr]
            for member in tar.getmembers()
        }
    members["linux/install.sh"] = members["linux/install.sh"] + b"\n# backdoor\n"
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(members):
            info_member = tarfile.TarInfo(name=name)
            info_member.size = len(members[name])
            tar.addfile(info_member, io.BytesIO(members[name]))
    tampered = tmp_path / "tampered.tar"
    tampered.write_bytes(tar_buffer.getvalue())

    with pytest.raises(BundleError, match="verify-bundle"):
        verify_daemon_bundle(tampered, info)

    # an INTERNALLY INCONSISTENT forgery (bundle digest fixed, stale member
    # digests) fails on members; a fully self-consistent forgery is out of
    # scope by design: the consumer pins the digest out of band (trust model)
    forged = DaemonBundleInfo(
        name=info.name,
        version=info.version,
        protocol=info.protocol,
        files=info.files,
        bundle_sha256=hashlib.sha256(tampered.read_bytes()).hexdigest(),
    )
    with pytest.raises(BundleError, match="verify-members"):
        verify_daemon_bundle(tampered, forged)


def test_sidecar_carries_the_contract(tmp_path: Path) -> None:
    info = build_daemon_bundle(tmp_path)
    sidecar = json.loads((tmp_path / "daemon.json").read_text())
    assert sidecar["protocol"] == 3
    assert set(sidecar["files"]) == {
        "linux/guestd",
        "linux/install.sh",
        "linux/guestd.service",
        "windows/Wire.cs",
        "windows/Store.cs",
        "windows/Exec.cs",
        "windows/Daemon.cs",
        "windows/Program.cs",
        "windows/install-daemon.ps1",
    }
    assert sidecar["bundle_sha256"] == info.bundle_sha256


def test_unpinned_toolchain_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Artifact builds refuse a toolchain that is not the pin (determinism gate)."""
    import inspect_ranges._channel.bundle as bundle_module

    fake = tmp_path / "fakego" / "go"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'go version go1.22.0 linux/amd64'\n")
    fake.chmod(0o755)
    monkeypatch.setattr(bundle_module, "PINNED_GO", tmp_path / "missing-go")
    monkeypatch.setenv("PATH", str(fake.parent))
    with pytest.raises(BundleError, match="toolchain"):
        build_daemon_bundle(tmp_path / "out")


def test_cli_daemon_bundle(tmp_path: Path) -> None:
    result = CliRunner().invoke(ranges, ["daemon-bundle", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "bundle sha256:" in result.output
    assert (tmp_path / bundle_file_name()).exists()
    assert (tmp_path / "daemon.json").exists()


def test_daemon_version_lockstep() -> None:
    """The bundle constant and both daemons' self-reported versions move together (drift has shipped before: the 3.5.0 entry reconciled a bundle label trailing at 3.3.0)."""
    from inspect_ranges._channel.bundle import _WINDOWS_DIR, DAEMON_VERSION, GO_SOURCE

    go = (GO_SOURCE / "daemon.go").read_text()
    cs = (_WINDOWS_DIR / "Daemon.cs").read_text()
    assert f'DaemonVersion  = "vsockd {DAEMON_VERSION} (go)"' in go
    assert f'public static string Version = "vsockd {DAEMON_VERSION} (windows)";' in cs


def test_install_script_locks_down_the_daemon_home() -> None:
    r"""The install must strip C:\\'s inherited ACEs before any content lands, grant by SID (goldens install on non-English Windows), keep work usable for profile-less user= execs, and remove the sources after the compile.

    C:\\'s default inheritance granted Authenticated Users Modify over the SYSTEM service binary: a harness-made local privesc on the exact machines whose task is local privesc (verified live, 2026-11-07). The capture scrub's `GUESTD_ACL_GUARD` is the other half of the contract.
    """
    from inspect_ranges._channel.bundle import _WINDOWS_DIR

    script = (_WINDOWS_DIR / "install-daemon.ps1").read_text()
    lockdown = script.index("icacls.exe C:\\guestd /inheritance:r")
    work = script.index("icacls.exe C:\\guestd\\work /inheritance:r")
    first_copy = script.index("Copy-Item")
    compile_at = script.index("csc.exe")
    cleanup = script.index("Remove-Item -Force C:\\guestd\\*.cs")
    # lockdown precedes any content landing; source cleanup follows the compile
    assert lockdown < first_copy and work < first_copy
    assert compile_at < cleanup
    # grants are SIDs, with Authenticated Users write-less outside work
    for grant in (
        "'*S-1-5-18:(OI)(CI)F'",
        "'*S-1-5-32-544:(OI)(CI)F'",
        "'*S-1-5-11:(RX)'",
        "'*S-1-5-11:(OI)(CI)(M)'",
    ):
        assert grant in script, grant
    # every icacls is asserted, never fire-and-forget
    assert script.count("& icacls.exe") == script.count('throw "icacls') == 2
