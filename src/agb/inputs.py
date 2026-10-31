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


class UnsupportedAction(RuntimeError):
    """Requested action cannot be performed on this platform/setup."""


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

    @staticmethod
    def _verify_cursor(sx: int, sy: int, tol: int = 2) -> None:
        """Confirm the cursor actually reached the target.

        Injected moves can be silently swallowed (active human mouse, UIPI
        blocking from elevated windows); clicking then would hit whatever app
        the cursor is really over. That must never happen.
        """
        px, py = pdi.position()
        if abs(px - sx) > tol or abs(py - sy) > tol:
            raise InputRejected(
                f"Cursor did not reach target: at ({px}, {py}), wanted ({sx}, {sy}); "
                "injected input is being blocked or overridden"
            )

    def click(self, x: int, y: int, scale: float, button: str = "left") -> None:
        sx, sy = self._to_screen(x, y, scale)
        pdi.moveTo(sx, sy)
        time.sleep(0.03)
        self._verify_cursor(sx, sy)
        pdi.click(button=button)

    def double_click(self, x: int, y: int, scale: float, button: str = "left") -> None:
        sx, sy = self._to_screen(x, y, scale)
        pdi.moveTo(sx, sy)
        time.sleep(0.03)
        self._verify_cursor(sx, sy)
        pdi.doubleClick(button=button)

    def move(self, x: int, y: int, scale: float) -> None:
        sx, sy = self._to_screen(x, y, scale)
        pdi.moveTo(sx, sy)
        self._verify_cursor(sx, sy)

    def drag(
        self, x1: int, y1: int, x2: int, y2: int, scale: float, button: str = "left"
    ) -> None:
        sx1, sy1 = self._to_screen(x1, y1, scale)
        sx2, sy2 = self._to_screen(x2, y2, scale)
        pdi.moveTo(sx1, sy1)
        self._verify_cursor(sx1, sy1)
        pdi.mouseDown(button=button)
        time.sleep(0.05)
        pdi.moveTo(sx2, sy2)
        self._verify_cursor(sx2, sy2)
        time.sleep(0.05)
        pdi.mouseUp(button=button)

    def type_text(self, text: str) -> None:
        pdi.typewrite(text, interval=0.02)

    def scroll(self, dy: int, x: int, y: int, scale: float) -> None:
        raise UnsupportedAction(
            "scroll is not implemented yet; it is counted as an invalid action"
        )

    def key(self, key: str, hold_ms: int = 0) -> None:
        if hold_ms:
            pdi.keyDown(key)
            time.sleep(hold_ms / 1000)
            pdi.keyUp(key)
        else:
            pdi.press(key)
