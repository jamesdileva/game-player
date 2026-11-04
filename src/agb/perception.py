"""Perception assists (architecture 5.6): L0 raw, L1 grid, L2 grid+OCR.

The overlay goes on the agent's view only; the recorder keeps clean frames
for the judge. Grid labels travel with the image through any rescaling,
which is what makes L1 robust against models that guess their coordinate frame.
L2 adds OCR text blocks with coordinates (used for evidence reading, e.g.
OSRS XP drops and chat lines).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageDraw

GRID_COLOR = (255, 255, 0)
OCR_COLOR = (0, 255, 255)
_MAX_OCR_BLOCKS = 15

try:  # optional dependency: pip install rapidocr-onnxruntime
    from rapidocr_onnxruntime import RapidOCR

    _OCR = RapidOCR()
except Exception:
    _OCR = None

HAS_OCR = _OCR is not None


@dataclass
class OcrBlock:
    text: str
    x: int
    y: int
    w: int
    h: int


def ocr_text(img: Image.Image) -> list[OcrBlock]:
    """OCR the image into text blocks with bounding boxes ([] without rapidocr)."""
    if _OCR is None:
        return []
    import numpy as np

    result, _ = _OCR(np.asarray(img))
    if not result:
        return []
    blocks: list[OcrBlock] = []
    for box, text, _score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        blocks.append(OcrBlock(
            text=str(text),
            x=int(min(xs)), y=int(min(ys)),
            w=int(max(xs) - min(xs)), h=int(max(ys) - min(ys)),
        ))
    return blocks[:_MAX_OCR_BLOCKS]


def find_text(img: Image.Image, pattern: str) -> list[OcrBlock]:
    """OCR blocks whose text matches a regex (deterministic evidence checks)."""
    rx = re.compile(pattern, re.IGNORECASE)
    return [b for b in ocr_text(img) if rx.search(b.text)]


def annotate_ocr(view: Image.Image) -> Image.Image:
    """Draw OCR boxes + text onto the view in cyan (L2)."""
    out = view.copy()
    d = ImageDraw.Draw(out)
    for b in ocr_text(view):
        d.rectangle([b.x, b.y, b.x + b.w, b.y + b.h], outline=OCR_COLOR, width=1)
        d.text((b.x, max(0, b.y - 12)), b.text[:30], fill=OCR_COLOR)
    return out


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
    if level == "L2":
        return annotate_ocr(grid_overlay(view))
    if level == "L1":
        return grid_overlay(view)
    return view
