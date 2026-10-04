"""Regenerate all diagrams and render them to SVG without a full docs build.

The Quarto docs build converts `.excalidraw` images automatically via the inspect-docs excalidraw filter; this script is for everything else: previewing diagrams during development, and producing the SVGs referenced by documents outside the docs project (e.g. `design/ranges-overview.qmd`).

Run from any directory:

    python3 docs/diagrams/preview.py

Requires Node.js. The converter's npm dependencies are installed on first use.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import containment
import dmz_pivot
import image_layers

DIAGRAMS = [dmz_pivot, containment, image_layers]


def main() -> None:
    """Regenerate every `.excalidraw` file and render each to `<name>.excalidraw.svg`."""
    diagrams_dir = Path(__file__).parent
    excalidraw_dir = (
        diagrams_dir.parent
        / "_extensions/meridianlabs-ai/inspect-docs/resources/excalidraw"
    )
    converter = excalidraw_dir / "excalidraw-to-svg.mjs"

    for module in DIAGRAMS:
        module.main()

    if not (excalidraw_dir / "node_modules").is_dir():
        print("installing converter dependencies (first use) ...")
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=excalidraw_dir,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    for src in sorted(diagrams_dir.glob("*.excalidraw")):
        svg = diagrams_dir / f"{src.name}.svg"
        subprocess.run(
            ["node", str(converter), str(src), str(svg), "--theme", "light"],
            check=True,
            capture_output=True,
        )
        print(f"  wrote {svg}")


if __name__ == "__main__":
    main()
