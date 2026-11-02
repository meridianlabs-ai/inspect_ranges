"""Every example's rendered nft ruleset must LOAD into a real kernel, not merely match pinned text: the 0.2.5 regression shipped rules the inet family refuses (`meta ibrname`), caught only at boot. Needs an unprivileged user namespace (unshare -rn) or passwordless-sudo ip netns; CI requires the privilege via INSPECT_RANGES_REQUIRE_NETNS."""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from inspect_ranges._build.manifest import BUILD_REALIZED_SECTIONS
from inspect_ranges._compiler import PlanOptions, render_bundle
from inspect_ranges._compiler.plan import (
    DEFAULT_ATTACKER_IMAGE,
    DEFAULT_ROUTER_IMAGE,
    image_file_name,
)
from inspect_ranges.schema import load_range
from inspect_ranges.types import RangeSpec

EXAMPLES = sorted(
    spec.parent.name
    for spec in (
        Path(__file__).parent.parent / "src" / "inspect_ranges" / "examples"
    ).glob("_*/range.yaml")
)
assert EXAMPLES, "the examples glob found nothing; the guard itself went quiet"

_LOAD_TIMEOUT_S = 60


def _fake_cache(tmp_path: Path, spec: RangeSpec) -> Path:
    """A cache carrying a placeholder for every image the TYPED spec references (plus both defaults), through the planner's own file-name rule; render needs presence, digests are advisory."""
    cache = tmp_path / "cache"
    cache.mkdir()
    references = {DEFAULT_ATTACKER_IMAGE, DEFAULT_ROUTER_IMAGE}
    for guest in [*spec.hosts, *spec.routers]:
        if guest.image is not None:  # routers may ride the default image
            references.add(guest.image)
    if spec.attacker.image is not None:
        references.add(spec.attacker.image)
    for reference in references:
        (cache / image_file_name(reference)).write_bytes(b"placeholder")
    return cache


def _load_ruleset(ruleset: Path) -> "subprocess.CompletedProcess[str] | None":
    """Run `nft -f` inside a scratch netns: unprivileged user namespaces where the kernel allows them, passwordless-sudo `ip netns` otherwise (CI and dev boxes), else `None` and the caller skips (or fails under INSPECT_RANGES_REQUIRE_NETNS). The netns name is unique per call so parallel workers never collide, and the in-command timeout bounds a hang the parent could not signal through sudo."""
    if subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0:
        return subprocess.run(
            [
                "unshare",
                "-rn",
                "timeout",
                str(_LOAD_TIMEOUT_S),
                "nft",
                "-f",
                str(ruleset),
            ],
            capture_output=True,
            text=True,
            timeout=_LOAD_TIMEOUT_S + 30,
        )
    name = f"ir-nft-{uuid.uuid4().hex[:12]}"
    added = subprocess.run(
        ["sudo", "-n", "ip", "netns", "add", name], capture_output=True
    )
    if added.returncode != 0:
        return None
    try:
        return subprocess.run(
            [
                "sudo",
                "-n",
                "ip",
                "netns",
                "exec",
                name,
                "timeout",
                str(_LOAD_TIMEOUT_S),
                "nft",
                "-f",
                str(ruleset),
            ],
            capture_output=True,
            text=True,
            timeout=_LOAD_TIMEOUT_S + 30,
        )
    finally:
        subprocess.run(["sudo", "-n", "ip", "netns", "delete", name])


def _render(spec: RangeSpec, tmp_path: Path, **options: object) -> Path:
    cache = _fake_cache(tmp_path, spec)
    render_bundle(
        spec,
        tmp_path / "bundle",
        PlanOptions(
            image_cache=cache,
            realized_sections=frozenset(BUILD_REALIZED_SECTIONS),
            **options,  # type: ignore[arg-type]
        ),
    )
    return tmp_path / "bundle" / "netns" / "range.nft"


def _assert_loads(ruleset: Path) -> None:
    loaded = _load_ruleset(ruleset)
    if loaded is None:
        if os.environ.get("INSPECT_RANGES_REQUIRE_NETNS") == "1":
            pytest.fail(
                "INSPECT_RANGES_REQUIRE_NETNS=1 but no scratch-netns privilege "
                "(user namespaces or passwordless sudo) is available"
            )
        pytest.skip("no scratch-netns privilege (user namespaces or sudo)")
    assert loaded.returncode == 0, loaded.stderr


@pytest.mark.parametrize("example", EXAMPLES)
def test_rendered_ruleset_loads_into_a_kernel(example: str, tmp_path: Path) -> None:
    """`nft -f` accepts the rendered ruleset inside a scratch netns; a rule the running kernel's families refuse fails here instead of at every operator's first boot. Content sections render as the build renders them (realizable), so no build manifest is needed."""
    examples = Path(__file__).parent.parent / "src" / "inspect_ranges" / "examples"
    spec = load_range(examples / example / "range.yaml")
    _assert_loads(_render(spec, tmp_path))


def test_probe_clamp_ruleset_loads_into_a_kernel(tmp_path: Path) -> None:
    """The probe-clamp table (appended only for probe-bearing plans) is the same renderer-variant class the 0.2.5 bug lived in, and no example exercises it; one probe-bearing render keeps it kernel-checked."""
    examples = Path(__file__).parent.parent / "src" / "inspect_ranges" / "examples"
    spec = load_range(examples / "_dmz_pivot" / "range.yaml")
    segment = spec.networks[0].name
    _assert_loads(_render(spec, tmp_path, probe_segments=frozenset({segment})))
