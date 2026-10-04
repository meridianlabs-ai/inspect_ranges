"""Generate `image-layers.excalidraw`, the image-sharing layer diagram for the overview.

See `image-layers-brief.md` for the design brief. Regenerate with `python3 docs/diagrams/image_layers.py` (or via `preview.py`, which also renders the SVG).
"""

from __future__ import annotations

from pathlib import Path

from _elements import (
    ATTACKER_BG,
    ATTACKER_STROKE,
    FONT_MONO,
    HARNESS_BG,
    HARNESS_STROKE,
    HOST_BG,
    HOST_STROKE,
    INFRA_BG,
    INFRA_STROKE,
    MUTED,
    Elements,
    make_arrow,
    make_rect,
    make_text,
    reset,
    save,
)


def build() -> Elements:
    """Build the image-layers elements."""
    reset()
    els: Elements = []

    # Per-VM overlays: private, ephemeral, one per guest.
    _, e = make_text(
        360,
        14,
        "per-VM overlays · copy-on-write · created instantly · deleted with the range",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    overlay_y, overlay_h, overlay_w = 46, 52, 150
    overlays = [
        (120, "web overlay", HOST_BG, HOST_STROKE),
        (285, "db overlay", HOST_BG, HOST_STROKE),
        (450, "agent overlay", ATTACKER_BG, ATTACKER_STROKE),
    ]
    golden_y = 140
    for x, label, bg, stroke in overlays:
        _, e = make_rect(
            x,
            overlay_y,
            overlay_w,
            overlay_h,
            label,
            bg=bg,
            stroke=stroke,
            stroke_width=2,
            font_size=14,
        )
        els += e
        _, e = make_arrow(
            x + overlay_w / 2,
            overlay_y + overlay_h,
            x + overlay_w / 2,
            golden_y,
            end_arrowhead=None,
        )
        els += e

    # Shared read-only tiers: golden additions on the upstream base.
    _, e = make_rect(
        120,
        golden_y,
        480,
        54,
        "golden additions · control daemon + settings",
        bg=HARNESS_BG,
        stroke=HARNESS_STROKE,
        font_size=14,
    )
    els += e
    _, e = make_rect(
        60,
        golden_y + 54,
        600,
        54,
        "upstream base image · ubuntu-24.04 cloud image",
        bg=INFRA_BG,
        stroke=INFRA_STROKE,
        font_size=14,
    )
    els += e
    _, e = make_text(
        360,
        golden_y + 54 + 54 + 18,
        "shared · read-only · published as layers, fetched only if a host lacks them",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    return els


def main() -> None:
    """Write `image-layers.excalidraw` next to this script."""
    save(Path(__file__).parent / "image-layers.excalidraw", build())


if __name__ == "__main__":
    main()
