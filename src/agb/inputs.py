"""Input injection, restricted to the game window (5.4; safety section 11).

Uses DirectInput-style scancodes via pydirectinput since many games ignore
plain virtual-key events. Any action that would land outside the game window
is refused, never clamped into range.
"""

from __future__ import annotations

import time

import pydirectinput as pdi

pdi.PAUSE = 0.02


class InputRejected(ValueError):
    pass


class WindowInput:
    """Translates agent-frame coordinates to screen coordinates inside the captured window."""

    def __init__(self, capture):
        self.cap = capture

    def _to_screen(self, x: int, y: int, scale: float) -> tuple[int, int]:
        r = self.cap.rect()
        sx = r["left"] + int(x / scale)
        sy = r["top"] + int(y / scale)
        lx, ty = r["left"], r["top"]
        inside = lx <= sx < lx + r["width"] and ty <= sy < ty + r["height"]
        if not inside:
            raise InputRejected(
                f"Action outside game window: screen ({sx}, {sy}) not in {r}"
            )
        return sx, sy

    def click(self, x: int, y: int, scale: float, button: str = "left") -> None:
        sx, sy = self._to_screen(x, y, scale)
        pdi.moveTo(sx, sy)
        time.sleep(0.03)
        pdi.click(button=button)

    def key(self, key: str, hold_ms: int = 0) -> None:
        if hold_ms:
            pdi.keyDown(key)
            time.sleep(hold_ms / 1000)
            pdi.keyUp(key)
        else:
            pdi.press(key)
