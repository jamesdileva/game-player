"""Global kill switch (default Ctrl+Alt+Q). Must work even if the game has focus."""

from __future__ import annotations

import threading

from pynput import keyboard

DEFAULT_COMBO = "<ctrl>+<alt>+q"


class KillSwitch:
    """Sets an event when the global hotkey fires; checked before every action.

    Note: pynput's GlobalHotKeys ignores *injected* key events by design, so
    only a physical key press on a real keyboard can trip it. Verify with a
    physical Ctrl+Alt+Q before every session (AGENTS.md safety rules).
    """

    def __init__(self, combo: str = DEFAULT_COMBO):
        self.event = threading.Event()
        self._listener = keyboard.GlobalHotKeys({combo: self.event.set})
        self._listener.daemon = True
        self._listener.start()

    @property
    def tripped(self) -> bool:
        return self.event.is_set()

    @property
    def armed(self) -> bool:
        """Listener thread is running and the hotkey combination registered."""
        return self._listener.is_alive() and bool(self._listener._hotkeys)
