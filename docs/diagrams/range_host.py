"""Generate `range-host.excalidraw`, the deployment-seam diagram for the overview.

See `range-host-brief.md` for the design brief. Regenerate with `python3 docs/diagrams/range_host.py` (or via `preview.py`, which also renders the SVG).
"""

from __future__ import annotations

from pathlib import Path

from _elements import (
    ARROW,
    ATTACKER_BG,
    ATTACKER_STROKE,
    CONTAINER_BG,
    CONTAINER_STROKE,
    CONTROL,
    CONTROL_BG,
    EVIDENCE,
    FONT_MONO,
    HARNESS_BG,
    HARNESS_STROKE,
    HOST_BG,
    HOST_STROKE,
    INFRA_BG,
    INFRA_STROKE,
    MUTED,
    TEXT,
    Elements,
    make_arrow,
    make_rect,
    make_text,
    reset,
    save,
)

# Light tint for the evidence store, matching the EVIDENCE stroke.
EVIDENCE_BG = "#fff4e6"


def build() -> Elements:
    """Build the deployment-seam elements."""
    reset()
    els: Elements = []

    # Left: the Inspect scaffold panel.
    _, e = make_rect(0, 0, 210, 180, bg=HARNESS_BG, stroke=HARNESS_STROKE)
    els += e
    _, e = make_text(16, 12, "Inspect scaffold", 14)
    els += e

    render_id, e = make_rect(
        15,
        52,
        180,
        30,
        "compile + render",
        bg="#ffffff",
        stroke=HARNESS_STROKE,
        font_size=13,
    )
    els += e
    loop_id, e = make_rect(
        15, 96, 180, 30, "agent loop", bg="#ffffff", stroke=HARNESS_STROKE, font_size=13
    )
    els += e
    # Deliberately flow-less: credentials never cross the boundary.
    _, e = make_rect(
        15,
        140,
        180,
        30,
        "model credentials",
        bg="#ffffff",
        stroke=HARNESS_STROKE,
        font_size=13,
    )
    els += e

    # The evidence store sits outside the scaffold panel: durable, append-only
    # storage the scaffold cannot rewrite.
    store_id, e = make_rect(
        0,
        204,
        210,
        36,
        "evidence store · append-only",
        bg=EVIDENCE_BG,
        stroke=EVIDENCE,
        font_size=12,
    )
    els += e

    # Right: the range host panel (heavy border echoing the containment
    # diagram's instance boundary).
    _, e = make_rect(
        380, 0, 260, 240, bg="#ffffff", stroke=CONTAINER_STROKE, stroke_width=2
    )
    els += e
    _, e = make_text(396, 12, "range host", 14)
    els += e
    _, e = make_text(
        396, 32, "one sample per instance", 11, MUTED, font_family=FONT_MONO
    )
    els += e

    applier_id, e = make_rect(
        390, 52, 100, 30, "applier", bg=INFRA_BG, stroke=INFRA_STROKE, font_size=13
    )
    els += e

    container_id, e = make_rect(
        390, 96, 230, 118, bg=CONTAINER_BG, stroke=CONTAINER_STROKE
    )
    els += e
    _, e = make_text(402, 104, "range container", 12)
    els += e

    # VM chips, each with the vsock notch from the containment diagram.
    chip_y, chip_h, chip_w = 146, 46, 62
    for x, label, bg, stroke in [
        (400, "router", INFRA_BG, INFRA_STROKE),
        (474, "target", HOST_BG, HOST_STROKE),
        (548, "agent", ATTACKER_BG, ATTACKER_STROKE),
    ]:
        _, e = make_rect(
            x, chip_y, chip_w, chip_h, label, bg=bg, stroke=stroke, font_size=11
        )
        els += e
        _, e = make_rect(
            x + chip_w / 2 - 10, chip_y - 5, 20, 10, bg=CONTROL_BG, stroke=CONTROL
        )
        els += e

    # Applier realizes the bundle into the range container.
    _, e = make_arrow(440, 82, 440, 96, start_id=applier_id, end_id=container_id)
    els += e

    # Trust boundary: all flow labels end left of x=360 so nothing collides.
    _, e = make_arrow(
        360, -8, 360, 248, color=MUTED, stroke_style="dashed", end_arrowhead=None
    )
    els += e
    _, e = make_text(360, -28, "trust boundary", 11, MUTED, align="center")
    els += e

    # Flow 1: the realization bundle, compile + render → applier.
    _, e = make_text(350, 47, "realization bundle", 12, TEXT, align="right")
    els += e
    _, e = make_arrow(
        197,
        67,
        388,
        67,
        color=ARROW,
        stroke_width=2,
        start_id=render_id,
        end_id=applier_id,
    )
    els += e

    # Flow 2: the control channel, agent loop ↔ range (both directions).
    _, e = make_text(350, 91, "control channel", 12, CONTROL, align="right")
    els += e
    channel_id, e = make_arrow(
        197,
        111,
        388,
        111,
        color=CONTROL,
        stroke_width=2,
        start_id=loop_id,
        end_id=container_id,
    )
    e[0]["startArrowhead"] = "triangle"
    els += e

    # Flow 3: evidence, range host → append-only store.
    _, e = make_text(350, 202, "evidence", 12, EVIDENCE, align="right")
    els += e
    _, e = make_arrow(
        378, 222, 212, 222, color=EVIDENCE, stroke_width=2, end_id=store_id
    )
    els += e

    return els


def main() -> None:
    """Write `range-host.excalidraw` next to this script."""
    save(Path(__file__).parent / "range-host.excalidraw", build())


if __name__ == "__main__":
    main()
