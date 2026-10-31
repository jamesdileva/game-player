"""Perception assists (architecture 5.6): L0 raw, L1 grid, L2 grid+OCR.

The overlay goes on the agent's view only; the recorder keeps clean frames
for the judge. Grid labels travel with the image through any rescaling,
which is what makes L1 robust against models that guess their coordinate frame.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

GRID_COLOR = (255, 255, 0)


def grid_overlay(img: Image.Image, step: int = 80) -> Image.Image:
    """Labeled coordinate grid: yellow lines every `step` px, labels on both axes."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    for x in range(0, out.width, step):
        d.line([(x, 0), (x, out.height)], fill=GRID_COLOR, width=1)
        d.text((x + 2, 2), str(x), fill=GRID_COLOR)
        d.text((x + 2, out.height - 12), str(x), fill=GRID_COLOR)
    for y in range(0, out.height, step):
        d.line([(0, y), (out.width, y)], fill=GRID_COLOR, width=1)
        d.text((2, y + 2), str(y), fill=GRID_COLOR)
        d.text((out.width - 30, y + 2), str(y), fill=GRID_COLOR)
    return out


def apply_assist(view: Image.Image, level: str) -> Image.Image:
    """Build the observation for the agent at the given assist level."""
    if level in ("L1", "L2"):
        return grid_overlay(view)
    return view
