"""Window capture: grabs the target window only, downscales for the agent (5.3).

Captures the window's CLIENT area (no title bar or borders): what the agent
sees is exactly the game, agent coordinates are client coordinates, and
clicks can never land on the title bar. Falls back to the full window rect
where the client area is unavailable.
"""

from __future__ import annotations

import sys
import time

import mss
import pygetwindow as gw
from PIL import Image


class WindowNotFoundError(RuntimeError):
    pass


def _client_rect(win) -> dict | None:
    """Client-area rect in screen coordinates (Windows only; None otherwise)."""
    if sys.platform != "win32":
        return None
    hwnd = getattr(win, "_hWnd", None)
    if not hwnd:
        return None
    import ctypes
    from ctypes import wintypes

    r = wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return {"left": pt.x, "top": pt.y, "width": r.right, "height": r.bottom}


def ensure_foreground(win) -> bool:
    """Bring the window to the foreground; the capture sees what covers it otherwise.

    pygetwindow's activate() fails from background processes because Windows
    blocks focus stealing; the ALT-key press releases the foreground lock.
    """
    try:
        if win.isActive:
            return True
    except Exception:
        pass
    try:
        win.activate()
        if win.isActive:
            return True
    except Exception:
        pass
    if sys.platform != "win32":
        return False
    hwnd = getattr(win, "_hWnd", None)
    if not hwnd:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x12, 0, 0, 0)  # ALT down: releases the foreground lock
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.keybd_event(0x12, 0, 2, 0)  # ALT up
    try:
        return bool(win.isActive)
    except Exception:
        return True


class WindowCapture:
    """Captures a window by title substring.

    ``grab`` returns the full-resolution frame (for the recorder and judge)
    and the downscaled agent view, plus the scale factor that maps agent-view
    coordinates back to client pixels: ``client_px = agent_px / scale``.
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
        return _client_rect(self.win) or {
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
