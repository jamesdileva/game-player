"""Paused mode (architecture 9.3): freeze the game during model inference.

Process-level suspend/resume via psutil — works for emulators and offline
native games. NEVER for online games (the server keeps simulating; OSRS stays
realtime — enforce at the task-spec level).
"""

from __future__ import annotations

import ctypes

import psutil


def pid_from_hwnd(hwnd: int) -> int | None:
    """Windows only: the pid owning a window handle."""
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


class GamePauser:
    """Suspends and resumes the game process around model inference."""

    def __init__(self, pid: int):
        try:
            self.proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self.proc = None
        self._suspended = False  # idempotent: nested suspend/resume stay balanced
        # a fresh run must start with the game live (a previous killed run
        # can leave it suspended mid-call)
        if self.proc is not None and self.proc.status() == psutil.STATUS_STOPPED:
            self.resume()

    @classmethod
    def from_window(cls, win) -> GamePauser | None:
        """Build from a pygetwindow handle; None when unavailable."""
        hwnd = getattr(win, "_hWnd", None)
        if not hwnd:
            return None
        try:
            pid = pid_from_hwnd(hwnd)
        except Exception:
            return None
        if not pid:
            return None
        try:
            return cls(pid)
        except psutil.NoSuchProcess:
            return None

    def suspend(self) -> None:
        if self.proc is None or self._suspended:
            return
        try:
            self.proc.suspend()
            self._suspended = True
        except psutil.NoSuchProcess:
            pass

    def resume(self) -> None:
        if self.proc is None or not self._suspended:
            return
        try:
            self.proc.resume()
            self._suspended = False
        except psutil.NoSuchProcess:
            pass

    def __enter__(self):
        self.suspend()
        return self

    def __exit__(self, *exc):
        self.resume()
        return False
