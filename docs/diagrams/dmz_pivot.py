"""Generate `dmz-pivot.excalidraw`, the topology diagram for the overview's example range.

See `dmz-pivot-brief.md` for the design brief. Regenerate with `python3 docs/diagrams/dmz_pivot.py` (or via `preview.py`, which also renders the SVG).
"""

from __future__ import annotations

from pathlib import Path

from _elements import (
    ATTACKER_BG,
    ATTACKER_STROKE,
    CONTAINER_BG,
    CONTAINER_STROKE,
    FONT_MONO,
    HOST_BG,
    HOST_STROKE,
    MUTED,
    Elements,
    make_arrow,
    make_rect,
    make_text,
    reset,
    save,
)


def build() -> Elements:
    """Build the dmz-pivot topology elements."""
    reset()
    els: Elements = []

    # Segment containers: dashed soft-gray broadcast domains. Overall width is
    # kept near 620 px so the diagram lands in a Word text column unscaled
    # enough that annotation type stays legible.
    seg_y, seg_h = 40, 185
    _, e = make_rect(
        0,
        seg_y,
        280,
        seg_h,
        bg=CONTAINER_BG,
        stroke=CONTAINER_STROKE,
        stroke_style="dashed",
    )
    els += e
    _, e = make_rect(
        420,
        seg_y,
        200,
        seg_h,
        bg=CONTAINER_BG,
        stroke=CONTAINER_STROKE,
        stroke_style="dashed",
    )
    els += e
    _, e = make_text(
        16, seg_y + 14, "dmz · 10.80.10.0/24", 12, MUTED, font_family=FONT_MONO
    )
    els += e
    _, e = make_text(
        433, seg_y + 14, "internal · 10.80.20.0/24", 12, MUTED, font_family=FONT_MONO
    )
    els += e

    # Hosts.
    box_y, box_h = 105, 60
    _, e = make_rect(
        20,
        box_y,
        112,
        box_h,
        "attacker",
        bg=ATTACKER_BG,
        stroke=ATTACKER_STROKE,
        stroke_width=2,
        font_size=14,
    )
    els += e
    _, e = make_text(
        76,
        box_y + box_h + 10,
        "entry: external",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    _, e = make_rect(
        152,
        box_y,
        108,
        box_h,
        "web",
        bg=HOST_BG,
        stroke=HOST_STROKE,
        stroke_width=2,
        font_size=14,
    )
    els += e
    _, e = make_text(
        206,
        box_y + box_h + 10,
        "10.80.10.10",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    _, e = make_rect(
        465,
        box_y,
        110,
        box_h,
        "db",
        bg=HOST_BG,
        stroke=HOST_STROKE,
        stroke_width=2,
        font_size=14,
    )
    els += e
    _, e = make_text(
        520,
        box_y + box_h + 10,
        "10.80.20.x",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    # Router between the segments, joined to each by a plain connector.
    router_id, e = make_rect(
        302, box_y, 96, box_h, "router", stroke_width=2, font_size=14
    )
    els += e
    mid_y = box_y + box_h / 2
    _, e = make_arrow(280, mid_y, 302, mid_y, end_arrowhead=None, end_id=router_id)
    els += e
    _, e = make_arrow(398, mid_y, 420, mid_y, end_arrowhead=None, start_id=router_id)
    els += e
    _, e = make_text(
        350,
        box_y + box_h + 10,
        "10.80.10.1\n10.80.20.1",
        12,
        MUTED,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    # The payload: the ACL, on its own line below the segments.
    _, e = make_text(
        310,
        seg_y + seg_h + 22,
        "acl: dmz → internal · tcp/5432 only",
        13,
        align="center",
        font_family=FONT_MONO,
    )
    els += e

    return els


def main() -> None:
    """Write `dmz-pivot.excalidraw` next to this script."""
    save(Path(__file__).parent / "dmz-pivot.excalidraw", build())


if __name__ == "__main__":
    main()
