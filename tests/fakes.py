"""Test doubles: a headless capture for loop tests (no window, no mouse)."""

from __future__ import annotations

import time

from PIL import Image


class FakeWin:
    title = "FakeGame | stage 1 | hits 0/3"
    isActive = True

    def activate(self) -> None:
        pass


class FakeCapture:
    """Satisfies the capture interface used by the loop, fully headless."""

    def __init__(self, width: int = 640, height: int = 480, color=(30, 30, 34)):
        self.width, self.height = width, height
        self.color = color
        self.win = FakeWin()

    def rect(self) -> dict:
        return {"left": 0, "top": 0, "width": self.width, "height": self.height}

    def grab(self):
        full = Image.new("RGB", (self.width, self.height), self.color)
        return full, full.copy(), 1.0, time.time()


class KillNever:
    """Kill-switch stand-in that never trips (headless)."""

    tripped = False
