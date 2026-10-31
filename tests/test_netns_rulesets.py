"""Every example's rendered nft ruleset must LOAD into a real kernel, not merely match pinned text: the 0.2.5 regression shipped rules the inet family refuses (`meta ibrname`), caught only at boot. Needs an unprivileged user namespace (unshare -rn); skips where the sandbox forbids it."""

import subprocess
import uuid
from pathlib import Path

import pytest
from inspect_ranges._compiler import PlanOptions, render_bundle
from inspect_ranges.schema import load_range

EXAMPLES = sorted(
    spec.parent.name
    for spec in (
        Path(__file__).parent.parent / "src" / "inspect_ranges" / "examples"
    ).glob("_*/range.yaml")
)


def _load_ruleset(ruleset: Path) -> subprocess.CompletedProcess[str] | None:
    """Run `nft -f` inside a scratch netns: unprivileged user namespaces where the kernel allows them, passwordless-sudo `ip netns` otherwise (CI and dev boxes), else `None` and the caller skips. The netns name is unique per call, so parallel test workers never collide."""
    if subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0:
        return subprocess.run(
            ["unshare", "-rn", "nft", "-f", str(ruleset)],
            capture_output=True,
            text=True,
        )
    name = f"ir-nft-{uuid.uuid4().hex[:12]}"
    added = subprocess.run(
        ["sudo", "-n", "ip", "netns", "add", name], capture_output=True
    )
    if added.returncode != 0:
        return None
    try:
        return subprocess.run(
            ["sudo", "-n", "ip", "netns", "exec", name, "nft", "-f", str(ruleset)],
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(["sudo", "-n", "ip", "netns", "delete", name])


def _fake_cache(tmp_path: Path, example_dir: Path) -> Path:
    """A cache carrying a placeholder file for every image the spec references (render only needs presence; digests are advisory at render time)."""
    import re

    cache = tmp_path / "cache"
    cache.mkdir()
    text = (example_dir / "range.yaml").read_text()
    for name in set(re.findall(r"image:\s*([\w.-]+)", text)) | {"attack"}:
        (cache / f"{name}.qcow2").write_bytes(b"placeholder")
    return cache


@pytest.mark.parametrize("example", EXAMPLES)
def test_rendered_ruleset_loads_into_a_kernel(example: str, tmp_path: Path) -> None:
    """`nft -f` accepts the rendered ruleset inside a scratch netns; a rule the running kernel's families refuse fails here instead of at every operator's first boot."""
    examples = Path(__file__).parent.parent / "src" / "inspect_ranges" / "examples"
    spec = load_range(examples / example / "range.yaml")
    cache = _fake_cache(tmp_path, examples / example)
    # content sections render as the build renders them (realizable), so a
    # content-bearing example needs no build manifest to produce its ruleset
    from inspect_ranges._build.manifest import BUILD_REALIZED_SECTIONS

    render_bundle(
        spec,
        tmp_path / "bundle",
        PlanOptions(
            image_cache=cache,
            realized_sections=frozenset(BUILD_REALIZED_SECTIONS),
        ),
    )
    loaded = _load_ruleset(tmp_path / "bundle" / "netns" / "range.nft")
    if loaded is None:
        pytest.skip("no scratch-netns privilege (user namespaces or sudo)")
    assert loaded.returncode == 0, loaded.stderr
