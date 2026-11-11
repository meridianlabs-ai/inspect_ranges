"""Golden derivation behavior through the public `derive_golden`/`list_images` surface, with the external commands faked and the daemon-bundle artifact built as a fixture."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from inspect_ranges._channel.bundle import DaemonBundleInfo, write_bundle
from inspect_ranges._runtime import DeriveError, derive_golden, list_images
from inspect_ranges._runtime.images import sha256_file


def fake_runner(argv: list[str], cwd: Path) -> None:
    """Stands in for qemu-img/virt-customize: creates or appends to the target overlay."""
    if argv[0] == "qemu-img":
        (cwd / argv[-2]).write_bytes(b"overlay:" + argv[argv.index("-b") + 1].encode())
    elif argv[0] == "virt-customize":
        target = cwd / argv[argv.index("-a") + 1]
        target.write_bytes(target.read_bytes() + b"|customized")
    else:  # pragma: no cover - unexpected command is a test bug
        raise AssertionError(f"unexpected command {argv}")


@pytest.fixture()
def vendor(tmp_path: Path) -> tuple[Path, str]:
    image = tmp_path / "noble-server-cloudimg-amd64.img"
    image.write_bytes(b"vendor-bytes")
    return image, hashlib.sha256(b"vendor-bytes").hexdigest()


def make_artifact(directory: Path, binary: bytes = b"#!fake-static-daemon") -> Path:
    """A real daemon-bundle artifact (production layout via the public `write_bundle`) with stand-in binary bytes."""
    write_bundle(directory, binary, version="3.0.0-test")
    return directory


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    return make_artifact(tmp_path / "artifacts")


def test_missing_artifact_names_the_publishing_command(
    tmp_path: Path, vendor: tuple[Path, str]
) -> None:
    image, digest = vendor
    with pytest.raises(DeriveError, match=r"\[resolve-daemon\].*daemon-bundle"):
        derive_golden(
            image,
            digest,
            tmp_path / "cache",
            runner=fake_runner,
            artifact_dir=tmp_path / "nowhere",
        )


def test_tampered_artifact_refuses(tmp_path: Path, vendor: tuple[Path, str]) -> None:
    image, digest = vendor
    artifact_dir = make_artifact(tmp_path / "artifacts")
    bundle = next(artifact_dir.glob("vsockd-bundle-*.tar"))
    bundle.write_bytes(bundle.read_bytes() + b"x")
    with pytest.raises(DeriveError, match=r"\[resolve-daemon\].*digest"):
        derive_golden(
            image,
            digest,
            tmp_path / "cache",
            runner=fake_runner,
            artifact_dir=artifact_dir,
        )


def test_derive_writes_golden_and_provenance(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"
    metadata, hit = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    assert not hit
    assert metadata.file == "noble-server-cloudimg-amd64-golden.qcow2"
    assert (cache / metadata.file).is_file()
    assert metadata.golden_sha256 == sha256_file(cache / metadata.file)
    assert metadata.vendor_sha256 == digest
    assert metadata.daemon is not None
    assert metadata.daemon.name == "vsockd"
    assert metadata.daemon.version == "3.0.0-test"
    sidecar_info = DaemonBundleInfo.model_validate_json(
        (artifact / "daemon.json").read_text()
    )
    assert metadata.daemon.sha256 == sidecar_info.bundle_sha256
    assert (cache / image.name).is_file(), (
        "vendor copied in for the relative backing ref"
    )
    sidecar = json.loads(
        (cache / "noble-server-cloudimg-amd64-golden.json").read_text()
    )
    assert sidecar["derivation_key"] == metadata.derivation_key


def test_derive_is_idempotent(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"
    first, hit_first = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )

    def refusing_runner(argv: list[str], cwd: Path) -> None:
        raise AssertionError("cache hit must not run commands")

    second, hit_second = derive_golden(
        image, digest, cache, runner=refusing_runner, artifact_dir=artifact
    )
    assert (not hit_first, hit_second) == (True, True)
    assert second.golden_sha256 == first.golden_sha256


def test_vendor_digest_mismatch_refuses_before_cache_writes(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, _ = vendor
    cache = tmp_path / "cache"
    with pytest.raises(DeriveError, match=r"\[verify-vendor\].*digest mismatch"):
        derive_golden(image, "0" * 64, cache, runner=fake_runner, artifact_dir=artifact)
    assert not cache.exists() or not any(cache.iterdir())


def test_unmanaged_file_is_never_clobbered(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"
    cache.mkdir()
    squatter = cache / "noble-server-cloudimg-amd64-golden.qcow2"
    squatter.write_bytes(b"hand-built")
    with pytest.raises(DeriveError, match=r"\[prepare\].*unmanaged"):
        derive_golden(image, digest, cache, runner=fake_runner, artifact_dir=artifact)
    assert squatter.read_bytes() == b"hand-built"


def test_failed_customize_leaves_no_cache_residue(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"

    def failing_runner(argv: list[str], cwd: Path) -> None:
        if argv[0] == "qemu-img":
            fake_runner(argv, cwd)
        else:
            raise subprocess.CalledProcessError(1, argv, "", "boom")

    with pytest.raises(DeriveError, match=r"\[customize\]"):
        derive_golden(
            image, digest, cache, runner=failing_runner, artifact_dir=artifact
        )
    # the per-name .lock file is deliberate persistent state (unlinking a
    # flock file races concurrent lockers); everything else must be gone
    residue = [
        p.name
        for p in cache.iterdir()
        if p.name != image.name and not p.name.endswith(".lock")
    ]
    assert residue == [], residue


def test_missing_host_tool_is_stage_named(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor

    def no_tool(argv: list[str], cwd: Path) -> None:
        raise FileNotFoundError(argv[0])

    with pytest.raises(DeriveError, match=r"\[create-overlay\].*not found"):
        derive_golden(
            image, digest, tmp_path / "cache", runner=no_tool, artifact_dir=artifact
        )


def test_corrupt_sidecar_is_unmanaged_to_both_list_and_derive(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """A non-conforming sidecar means unmanaged everywhere: list flags the image, derive refuses to touch it."""
    image, digest = vendor
    cache = tmp_path / "cache"
    metadata, _ = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    sidecar = cache / "noble-server-cloudimg-amd64-golden.json"
    sidecar.write_text("{not json")
    managed, _, unmanaged = list_images(cache)
    assert managed == []
    assert metadata.file in unmanaged
    with pytest.raises(DeriveError, match=r"\[prepare\].*not a valid provenance"):
        derive_golden(image, digest, cache, runner=fake_runner, artifact_dir=artifact)
    assert sidecar.read_text() == "{not json", "derive must not touch it"


def test_tampered_in_cache_vendor_rederives_on_hit(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """A cache hit stands only on an untampered backing file; a swapped in-cache vendor re-derives from the verified source."""
    image, digest = vendor
    cache = tmp_path / "cache"
    metadata, _ = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    (cache / image.name).write_bytes(b"tampered")
    repaired, hit = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    assert not hit
    assert (cache / image.name).read_bytes() == b"vendor-bytes"
    assert repaired.golden_sha256 == metadata.golden_sha256


def test_partial_vendor_copy_is_replaced_not_bricked(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """A partial in-cache vendor (killed mid-copy) is atomically replaced from the verified source, never refused."""
    image, digest = vendor
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / image.name).write_bytes(b"vendor-by")  # truncated copy
    metadata, hit = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    assert not hit
    assert (cache / image.name).read_bytes() == b"vendor-bytes"
    assert metadata.vendor_sha256 == digest


def test_sidecar_without_golden_is_repaired_not_refused(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """The crash window (sidecar renamed, golden rename lost) self-heals on the next derive."""
    image, digest = vendor
    cache = tmp_path / "cache"
    metadata, _ = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    (cache / metadata.file).unlink()
    repaired, hit = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    assert not hit
    assert (cache / metadata.file).is_file()
    assert repaired.golden_sha256 == metadata.golden_sha256


def test_dotted_names_map_to_distinct_files_and_sidecars(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"
    first, _ = derive_golden(
        image,
        digest,
        cache,
        name="ubuntu-24.04",
        runner=fake_runner,
        artifact_dir=artifact,
    )
    second, _ = derive_golden(
        image,
        digest,
        cache,
        name="ubuntu-24.10",
        runner=fake_runner,
        artifact_dir=artifact,
    )
    assert first.file == "ubuntu-24.04.qcow2"
    assert second.file == "ubuntu-24.10.qcow2"
    assert (cache / "ubuntu-24.04.json").is_file()
    assert (cache / "ubuntu-24.10.json").is_file()
    managed, _, _ = list_images(cache)
    assert {m.file for m in managed} >= {"ubuntu-24.04.qcow2", "ubuntu-24.10.qcow2"}


def test_list_images_separates_managed_and_unmanaged(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    cache = tmp_path / "cache"
    derive_golden(image, digest, cache, runner=fake_runner, artifact_dir=artifact)
    (cache / "handmade.qcow2").write_bytes(b"x")
    managed, _, unmanaged = list_images(cache)
    assert [m.file for m in managed] == ["noble-server-cloudimg-amd64-golden.qcow2"]
    assert unmanaged == ["handmade.qcow2"]


def test_daemon_pin_mismatch_refuses(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """The out-of-band pin is the provenance check: a self-consistent artifact that does not match it refuses."""
    image, digest = vendor
    with pytest.raises(
        DeriveError, match=r"\[resolve-daemon\].*does not match the pin"
    ):
        derive_golden(
            image,
            digest,
            tmp_path / "cache",
            runner=fake_runner,
            artifact_dir=artifact,
            daemon_sha256="f" * 64,
        )


def test_protocol_skewed_artifact_refuses(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    image, digest = vendor
    sidecar = artifact / "daemon.json"
    info = DaemonBundleInfo.model_validate_json(sidecar.read_text())
    skewed = info.model_dump()
    skewed["protocol"] = 99
    sidecar.write_text(DaemonBundleInfo.model_construct(**skewed).model_dump_json())
    with pytest.raises(DeriveError, match=r"\[resolve-daemon\].*protocol 99"):
        derive_golden(
            image,
            digest,
            tmp_path / "cache",
            runner=fake_runner,
            artifact_dir=artifact,
        )


def test_list_cmd_labels_unparseable_recipe_version(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """A non-integer recipe version must not be labeled with an ordering that could not be computed (the doctor's three-way split, mirrored)."""
    import json as json_module

    from click.testing import CliRunner
    from inspect_ranges._cli.main import ranges

    image, digest = vendor
    cache = tmp_path / "cache"
    metadata, _ = derive_golden(
        image, digest, cache, runner=fake_runner, artifact_dir=artifact
    )
    sidecar = cache / (Path(metadata.file).stem + ".json")
    doctored = json_module.loads(sidecar.read_text())
    doctored["recipe_version"] = "beta"
    sidecar.write_text(json_module.dumps(doctored))
    result = CliRunner().invoke(ranges, ["images", "list", "--image-cache", str(cache)])
    assert result.exit_code == 0
    assert "RECIPE UNPARSEABLE" in result.output
    assert "STALE RECIPE" not in result.output


def test_prune_reporters_apply_the_live_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-2 gap: images list/doctor/prune must agree on one liveness definition (recorded manifests UNION running projects' boot.json files)."""
    import json

    from inspect_ranges._build.capture import live_project_files
    from inspect_ranges._build.manifest import recorded_realized_files
    from inspect_ranges._runtime.ownership import owner_record, write_owner

    state = tmp_path / "state"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "boot.json").write_text(
        json.dumps({"guests": [{"name": "web", "image_file": "live-web-abc.qcow2"}]})
    )
    write_owner(state, owner_record("ir-live-x", "live", "0" * 64, bundle))
    live = recorded_realized_files(tmp_path / "no-builds") | live_project_files(state)
    assert "live-web-abc.qcow2" in live


def test_import_image_lands_flattened_with_an_imported_sidecar(tmp_path: Path) -> None:
    """An import flattens any backing chain into one self-contained cache file and records a kind=imported sidecar: no daemon pin, the source's own name and digest as provenance, the operator's notes; a second import of the name refuses."""
    import subprocess

    from inspect_ranges._runtime.images import (
        DeriveError,
        ImageMetadata,
        import_image,
        sha256_file,
    )

    base = tmp_path / "appliance-base.qcow2"
    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", str(base), "4M"],
        check=True,
        capture_output=True,
    )
    source = tmp_path / "appliance-prepped.qcow2"
    subprocess.run(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            str(base),
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    cache = tmp_path / "cache"
    metadata = import_image(source, "acme-router-9.9", cache, notes="prepped offline")
    assert metadata.resolved_kind == "imported" and metadata.chainless
    assert metadata.daemon is None
    assert metadata.vendor_file == "appliance-prepped.qcow2"
    assert metadata.vendor_sha256 == sha256_file(source)
    assert metadata.notes == "prepped offline"
    landed = cache / metadata.file
    assert landed.is_file()
    assert metadata.golden_sha256 == sha256_file(landed)
    info = subprocess.run(
        ["qemu-img", "info", "--output=json", str(landed)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "backing-filename" not in info  # the chain flattened on the way in
    reloaded = ImageMetadata.model_validate_json(
        (cache / (metadata.file.removesuffix(".qcow2") + ".json")).read_text()
    )
    assert reloaded.resolved_kind == "imported"
    with pytest.raises(DeriveError, match="never overwrite"):
        import_image(source, "acme-router-9.9", cache)


def test_sidecar_kind_resolution_and_daemon_rule(tmp_path: Path) -> None:
    """Legacy sidecars (no kind) resolve by the .iso suffix; a daemonless sidecar refuses unless imported."""
    import pydantic
    from inspect_ranges._runtime.images import DaemonPin, ImageMetadata

    def sidecar(**overrides: object) -> ImageMetadata:
        base: dict[str, object] = {
            "name": "x",
            "file": "x.qcow2",
            "recipe_version": "5",
            "derivation_key": "k" * 64,
            "vendor_file": "noble.img",
            "vendor_sha256": "a" * 64,
            "daemon": DaemonPin(name="vsockd", version="3.3.0", sha256="d" * 64),
            "golden_sha256": "b" * 64,
            "created": "2026-11-01T00:00:00+00:00",
        }
        base.update(overrides)
        return ImageMetadata.model_validate(base)

    assert sidecar().resolved_kind == "golden" and not sidecar().chainless
    assert sidecar(vendor_file="server.iso").resolved_kind == "installed"
    assert sidecar(vendor_file="server.iso").chainless
    assert sidecar(kind="imported", daemon=None).chainless
    with pytest.raises(pydantic.ValidationError, match="only imported"):
        sidecar(daemon=None)


def test_interrupted_import_heals_and_bad_names_refuse(tmp_path: Path) -> None:
    """Round-2 appliance review I1/N3: a sidecar without its image is an interrupted import (the sidecar lands first) and re-importing the name heals it; healing never clobbers a non-imported sidecar, and an unpublishable `--as` name refuses up front."""
    import subprocess

    from inspect_ranges._runtime.images import DeriveError, import_image

    source = tmp_path / "fw-disk.qcow2"
    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", str(source), "4M"],
        check=True,
        capture_output=True,
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    # the interrupted-import shape: an imported sidecar whose image never landed
    first = import_image(source, "fw", cache)
    (cache / first.file).unlink()
    healed = import_image(source, "fw", cache)
    assert (cache / healed.file).is_file()
    # a sidecar of any other kind is a mid-landing chain: never clobbered
    (cache / healed.file).unlink()
    (cache / "fw.json").write_text('{"kind": "golden"}')
    with pytest.raises(DeriveError, match="does not record an imported image"):
        import_image(source, "fw", cache)
    # the user-facing entry refuses an unpublishable name before any work
    with pytest.raises(DeriveError, match="not a legal image name"):
        import_image(source, "my fw", cache)


def _qcow2_vendor(tmp_path: Path, virtual_size: int) -> tuple[Path, str]:
    """A stand-in vendor carrying a real qcow2 header with the given virtual size."""
    header = b"QFI\xfb" + (3).to_bytes(4, "big") + b"\x00" * 16
    header += virtual_size.to_bytes(8, "big") + b"\x00" * 32
    image = tmp_path / "big-vendor.qcow2"
    image.write_bytes(header)
    return image, hashlib.sha256(header).hexdigest()


def recording_runner(record: list[list[str]]):
    def runner(argv: list[str], cwd: Path) -> None:
        record.append(list(argv))
        fake_runner(argv, cwd)

    return runner


def test_overlay_covers_large_vendor(tmp_path: Path, artifact: Path) -> None:
    """A large vendor gets an overlay of its own virtual size.

    A fixed size would truncate the disk under the partition table and the
    guest would fail inspection.
    """
    fifty_g = 50 * 1024**3
    image, digest = _qcow2_vendor(tmp_path, fifty_g)
    record: list[list[str]] = []
    derive_golden(
        image,
        digest,
        tmp_path / "cache",
        runner=recording_runner(record),
        artifact_dir=artifact,
    )
    create = next(argv for argv in record if argv[:2] == ["qemu-img", "create"])
    assert create[-1] == str(fifty_g)


def test_overlay_keeps_floor_for_small_vendor(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """Small (or non-qcow2 stand-in) vendors keep the 10G floor."""
    image, digest = vendor
    record: list[list[str]] = []
    derive_golden(
        image,
        digest,
        tmp_path / "cache",
        runner=recording_runner(record),
        artifact_dir=artifact,
    )
    create = next(argv for argv in record if argv[:2] == ["qemu-img", "create"])
    assert create[-1] == str(10 * 1024**3)


def test_customize_tolerates_existing_agent_user(
    tmp_path: Path, vendor: tuple[Path, str], artifact: Path
) -> None:
    """Re-deriving an image that already carries the agent user must not abort.

    Previously derived (or otherwise agent-carrying) disks hit useradd's
    already-exists failure without the guard.
    """
    image, digest = vendor
    record: list[list[str]] = []
    derive_golden(
        image,
        digest,
        tmp_path / "cache",
        runner=recording_runner(record),
        artifact_dir=artifact,
    )
    customize = next(argv for argv in record if argv[0] == "virt-customize")
    command = customize[customize.index("--run-command") + 1]
    assert command.startswith("id -u agent >/dev/null 2>&1 || useradd")
