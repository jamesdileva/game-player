"""Environment setup and shared configuration helpers."""

from __future__ import annotations

import sys


def ensure_dpi_awareness() -> None:
    """Per-monitor DPI awareness so window coords match physical pixels.

    Mismatched scaling is the most common capture/click bug (implementation-guide 15).
    Call once at process start, before any window enumeration or capture.
    """
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
