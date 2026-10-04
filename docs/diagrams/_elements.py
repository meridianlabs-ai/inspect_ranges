"""Excalidraw element constructors shared by the diagram generators in this directory.

Adapted from the diagram helpers used across the Meridian Labs docs (`inspect_petri`, `petri_bloom`, `inspect_steward`): flat JSON element constructors with clean lines (roughness 0), the Excalidraw font ids (2 = sans, 3 = mono), and rough text metrics. Estimates only need to be close because `.excalidraw` files carry pre-computed text dimensions, and the character advance of 0.6 em matches the measurement mock in the inspect-docs SVG converter.

Both the `.excalidraw` file and its rendered SVG are committed (the SVG force-added past the docs build's generated gitignore), so documents outside the docs project (e.g. `design/ranges-overview.qmd`) render from a fresh clone with no regeneration step. After changing a generator, run `preview.py` and commit the refreshed SVGs alongside it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

Element = dict[str, Any]
Elements = list[Element]
ElementResult = tuple[str, Elements]

# Excalidraw font ids (1 = hand-drawn, 2 = Helvetica, 3 = monospace).
FONT_SANS = 2
FONT_MONO = 3

# House palette (shared with the sibling projects' docs diagrams).
TEXT = "#1e1e1e"
MUTED = "#868e96"
ARROW = "#868e96"

# Segments and grouping containers.
CONTAINER_BG = "#f8f9fa"
CONTAINER_STROKE = "#adb5bd"

# Target hosts (blue).
HOST_BG = "#dbe4ff"
HOST_STROKE = "#4263eb"

# Attacker (red).
ATTACKER_BG = "#ffe3e3"
ATTACKER_STROKE = "#e03131"

# Routers and infrastructure (gray).
INFRA_BG = "#e9ecef"
INFRA_STROKE = "#495057"

# Trusted harness components (indigo).
HARNESS_BG = "#e4e9fc"
HARNESS_STROKE = "#4263eb"

# Control plane (violet) and evidence (amber).
CONTROL = "#7048e8"
CONTROL_BG = "#e5dbff"
EVIDENCE = "#e67700"

_UPDATED = 1712345678000
_counter = 0


def reset() -> None:
    """Reset ids and seeds so each diagram builds deterministically regardless of what was generated before it in the same process."""
    global _counter
    _counter = 0
    random.seed(42)


def _id() -> str:
    global _counter
    _counter += 1
    return f"el_{_counter}"


def _seed() -> int:
    return random.randint(1, 2**31 - 1)


def text_dims(content: str, font_size: int) -> tuple[float, float]:
    """Estimate the bounding box of text, matching the converter's 0.6 em advance mock."""
    lines = content.split("\n")
    w = max(len(line) for line in lines) * font_size * 0.6
    h = len(lines) * font_size * 1.25
    return w, h


def _baseline(content: str, font_size: int) -> int:
    lines = content.split("\n")
    return int((len(lines) - 1) * font_size * 1.25 + font_size)


def _common(kind: str, x: float, y: float, w: float, h: float) -> Element:
    return {
        "id": _id(),
        "type": kind,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": TEXT,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _seed(),
        "version": 1,
        "versionNonce": _seed(),
        "isDeleted": False,
        "boundElements": None,
        "updated": _UPDATED,
        "link": None,
        "locked": False,
    }


def make_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    label: str | None = None,
    bg: str = INFRA_BG,
    stroke: str = INFRA_STROKE,
    stroke_width: int = 1,
    stroke_style: str = "solid",
    font_size: int = 14,
    font_family: int = FONT_SANS,
    label_color: str = TEXT,
    rounded: bool = True,
) -> ElementResult:
    """Create a rectangle, optionally with a centered bound label. Returns `(rect_id, elements)`."""
    rect = _common("rectangle", x, y, w, h)
    rect.update(
        strokeColor=stroke,
        backgroundColor=bg,
        strokeWidth=stroke_width,
        strokeStyle=stroke_style,
        roundness={"type": 3} if rounded else None,
    )
    elements: Elements = [rect]

    if label is not None:
        tw, th = text_dims(label, font_size)
        text = _common("text", x + (w - tw) / 2, y + (h - th) / 2, tw, th)
        text.update(
            strokeColor=label_color,
            text=label,
            fontSize=font_size,
            fontFamily=font_family,
            textAlign="center",
            verticalAlign="middle",
            baseline=_baseline(label, font_size),
            containerId=rect["id"],
            originalText=label,
            autoResize=True,
            lineHeight=1.25,
        )
        rect["boundElements"] = [{"id": text["id"], "type": "text"}]
        elements.append(text)

    return rect["id"], elements


def make_text(
    x: float,
    y: float,
    content: str,
    font_size: int = 14,
    color: str = TEXT,
    align: str = "left",
    font_family: int = FONT_SANS,
) -> ElementResult:
    """Create standalone text. `x` is the left edge for `align="left"`, the center for `align="center"`, and the right edge for `align="right"`. Returns `(text_id, elements)`."""
    tw, th = text_dims(content, font_size)
    if align == "center":
        x -= tw / 2
    elif align == "right":
        x -= tw

    text = _common("text", x, y, tw, th)
    text.update(
        strokeColor=color,
        text=content,
        fontSize=font_size,
        fontFamily=font_family,
        textAlign=align,
        verticalAlign="top",
        baseline=_baseline(content, font_size),
        containerId=None,
        originalText=content,
        autoResize=True,
        lineHeight=1.25,
    )
    return text["id"], [text]


def make_arrow(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str = ARROW,
    stroke_width: int = 1,
    stroke_style: str = "solid",
    end_arrowhead: str | None = "triangle",
    start_id: str | None = None,
    end_id: str | None = None,
) -> ElementResult:
    """Create a straight arrow (or a plain connector when `end_arrowhead` is `None`). Returns `(arrow_id, elements)`."""
    dx, dy = x2 - x1, y2 - y1
    arrow = _common("arrow", x1, y1, abs(dx), abs(dy))
    arrow.update(
        strokeColor=color,
        strokeWidth=stroke_width,
        strokeStyle=stroke_style,
        roundness={"type": 2},
        points=[[0, 0], [dx, dy]],
        lastCommittedPoint=None,
        startBinding=(
            {"elementId": start_id, "focus": 0, "gap": 4, "fixedPoint": None}
            if start_id
            else None
        ),
        endBinding=(
            {"elementId": end_id, "focus": 0, "gap": 4, "fixedPoint": None}
            if end_id
            else None
        ),
        startArrowhead=None,
        endArrowhead=end_arrowhead,
    )
    return arrow["id"], [arrow]


def wrap(elements: Elements) -> Element:
    """Wrap elements in the Excalidraw file envelope."""
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {"gridSize": 20, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }


def save(path: Path, elements: Elements) -> None:
    """Write elements to an `.excalidraw` file."""
    path.write_text(json.dumps(wrap(elements), indent=2) + "\n")
    print(f"  wrote {path}")
