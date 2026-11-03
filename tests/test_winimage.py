"""Windows installer answer-file pins: the per-variant install contract (windows11-client-v1) and the password-escaping rule (phase review round 1, finding A3) — an unescaped password burns the whole install timeout instead of failing a parse."""

from pathlib import Path
from xml.etree import ElementTree

import pytest
from inspect_ranges._runtime.images import DeriveError
from inspect_ranges._runtime.winimage import (
    WINDOWS_OS_VARIANTS,
    _derivation_key,  # pyright: ignore[reportPrivateUsage]
    install_windows_golden,
    render_install_unattend,
)

_NS = "{urn:schemas-microsoft-com:unattend}"


@pytest.mark.parametrize("variant_key", sorted(WINDOWS_OS_VARIANTS))
def test_install_unattend_parses_with_a_hostile_password(variant_key: str) -> None:
    """Every interpolation point in every variant's answer file survives an XML-hostile password; the rendered document parses and carries the escaped value at both password sites (AdministratorPassword + AutoLogon)."""
    hostile = """<&>"'pass</Value>"""
    rendered = render_install_unattend(WINDOWS_OS_VARIANTS[variant_key], hostile)
    root = ElementTree.fromstring(rendered)
    values = [
        element.text
        for element in root.iter(f"{_NS}Value")
        if element.text and "pass" in element.text
    ]
    assert len(values) >= 2, "both password sites must carry the value"
    assert all(v == hostile for v in values), "escaping must round-trip exactly"
    # the password is the only caller data; every template placeholder renders
    assert "__" not in rendered
    # client OOBE needs the full wizard skipped, not just the named screens
    # (measured: Windows 11 stops at the country/region screen without these)
    assert "<SkipMachineOOBE>true</SkipMachineOOBE>" in rendered
    assert "<SkipUserOOBE>true</SkipUserOOBE>" in rendered


def test_variant_answer_files_pin_the_install_contract() -> None:
    """server-2022 keeps the proven BIOS shape (MBR active partition, image 1, 2k22 drivers, no product key); 11 renders the UEFI shape (GPT with ESP + MSR, OS on partition 3, image 6 with the documented edition-selection key, w11 drivers)."""
    server = render_install_unattend(WINDOWS_OS_VARIANTS["server-2022"], "pw")
    win11 = render_install_unattend(WINDOWS_OS_VARIANTS["11"], "pw")

    assert "E:\\amd64\\2k22" in server
    assert "<Active>true</Active>" in server
    assert "<Type>EFI</Type>" not in server
    assert "<Key>/IMAGE/INDEX</Key><Value>1</Value>" in server
    assert (
        "<InstallTo><DiskID>0</DiskID><PartitionID>1</PartitionID></InstallTo>"
        in server
    )
    assert "<ProductKey>" not in server

    assert "E:\\amd64\\w11" in win11
    assert "<Type>EFI</Type>" in win11
    assert "<Type>MSR</Type>" in win11
    assert "<Active>true</Active>" not in win11, "secure boot refuses MBR"
    assert "<Key>/IMAGE/INDEX</Key><Value>6</Value>" in win11
    assert (
        "<InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo>" in win11
    )
    assert "<ProductKey>" in win11

    # the client specialize facts (measured: no-network OOBE parks without
    # BypassNRO, device encryption auto-arms against the TPM, the built-in
    # Administrator starts disabled and takes its password here); servers
    # carry none of them
    assert "BypassNRO" in win11 and "BypassNRO" not in server
    assert win11.count("/v PreventDeviceEncryption /t REG_DWORD") == 2
    assert "net user Administrator /active:yes" in win11
    assert 'net user Administrator "pw"' in win11
    assert "PreventDeviceEncryption" not in server
    assert "net user" not in server


def test_the_os_variant_enters_the_derivation_key() -> None:
    """Same media, daemon, and password: one OS variant must never cache-hit another's golden."""
    keys = {
        _derivation_key(variant, "i" * 64, "v" * 64, "d" * 64, "pw")
        for variant in WINDOWS_OS_VARIANTS.values()
    }
    assert len(keys) == len(WINDOWS_OS_VARIANTS)


def test_cli_os_choices_track_the_variant_table() -> None:
    """`images derive-windows --os` offers exactly the variant table's keys (the CLI re-encodes them as a literal to keep the module import light; this pin turns drift into a failure)."""
    import click
    from inspect_ranges._cli.imagescmd import derive_windows

    param = next(p for p in derive_windows.params if p.name == "os_variant")
    assert isinstance(param.type, click.Choice)
    assert sorted(param.type.choices) == sorted(WINDOWS_OS_VARIANTS)


def test_client_refuses_a_cmd_hostile_admin_password(tmp_path: Path) -> None:
    """The client specialize block carries the password on a cmd line; characters cmd cannot quote refuse up front (the paths here do not exist, proving the refusal precedes any media check)."""
    with pytest.raises(DeriveError, match="cmd line"):
        install_windows_golden(
            tmp_path / "a.iso",
            "0" * 64,
            tmp_path / "v.iso",
            "0" * 64,
            tmp_path,
            os_variant="11",
            admin_password='has"quote',
        )


def test_unknown_os_variant_refuses_before_touching_media(tmp_path: Path) -> None:
    """An unknown variant names the supported set and fails before any media check (the paths here do not exist)."""
    with pytest.raises(DeriveError, match="unknown Windows OS variant"):
        install_windows_golden(
            tmp_path / "a.iso",
            "0" * 64,
            tmp_path / "v.iso",
            "0" * 64,
            tmp_path,
            os_variant="server-2025",
        )
