"""Window capture: grabs the target window only, downscales for the agent (5.3)."""

from __future__ import annotations

import time

import mss
import pygetwindow as gw
from PIL import Image


class WindowNotFoundError(RuntimeError):
    pass


class WindowCapture:
    """Captures a window by title substring.

    ``grab`` returns the full-resolution frame (for the recorder and judge)
    and the downscaled agent view, plus the scale factor that maps agent-view
    coordinates back to window pixels: ``window_px = agent_px / scale``.
    """

    def __init__(self, title_substring: str, max_w: int = 1280, max_h: int = 720):
        wins = [
            w
            for w in gw.getAllWindows()
            if title_substring.lower() in (w.title or "").lower() and w.width > 0 and w.height > 0
        ]
        if not wins:
            raise WindowNotFoundError(f"No visible window matching {title_substring!r}")
        self.win = wins[0]
        self.max_w, self.max_h = max_w, max_h
        self._sct = mss.MSS()

    def rect(self) -> dict:
        return {
            "left": self.win.left,
            "top": self.win.top,
            "width": self.win.width,
            "height": self.win.height,
        }

    def grab(self) -> tuple[Image.Image, Image.Image, float, float]:
        """Returns (full_res, agent_view, scale, timestamp)."""
        shot = self._sct.grab(self.rect())
        full = Image.frombytes("RGB", shot.size, shot.rgb)
        scale = min(self.max_w / full.width, self.max_h / full.height, 1.0)
        view = full.resize((max(1, int(full.width * scale)), max(1, int(full.height * scale))))
        return full, view, scale, time.time()
