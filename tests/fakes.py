"""Test doubles: a headless capture for loop tests (no window, no mouse)."""

from __future__ import annotations

import threading
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
    """Kill-switch stand-in: trips only when a test sets the event."""

    def __init__(self):
        self.event = threading.Event()

    @property
    def tripped(self) -> bool:
        return self.event.is_set()


from testbed.fakegame import FakeGameState  # noqa: E402


class FakeWinWithState:
    """Window stand-in whose title mirrors a FakeGameState, like the real game."""

    isActive = True

    def __init__(self, state: FakeGameState):
        self._state = state

    @property
    def title(self) -> str:
        s = self._state
        return f"FakeGame | stage {s.stage} | hits {s.hits}/{s.hits_needed}"

    def activate(self) -> None:
        pass


class RecordingInput:
    """Input stand-in: records clicks and feeds them to the fake game state.

    Replaces real mouse injection in headless loop tests - the full
    capture -> parse -> dispatch -> game-state pipeline runs without
    touching the desktop.
    """

    def __init__(self, state: FakeGameState):
        self.state = state
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []

    def click(self, x, y, scale=1.0, button="left"):
        self.clicks.append((int(x), int(y)))
        self.state.register_click(int(x), int(y))

    def double_click(self, x, y, scale=1.0, button="left"):
        self.click(x, y, scale, button)

    def move(self, x, y, scale=1.0):
        self.clicks.append((int(x), int(y)))

    def drag(self, *a, **k):
        pass

    def type_text(self, text):
        self.keys.append(text)

    def scroll(self, *a, **k):
        from agb.inputs import UnsupportedAction

        raise UnsupportedAction("scroll unimplemented (as in WindowInput)")

    def key(self, key, hold_ms=0):
        self.keys.append(key)


class FakeGameHarness:
    """Headless game + input + window bundle for loop tests."""

    def __init__(self, square_xy=(400, 300), hits_needed=3):
        self.state = FakeGameState(
            width=640, height=480, square_xy=square_xy, hits_needed=hits_needed
        )
        self.win = FakeWinWithState(self.state)
        self.inp = RecordingInput(self.state)

    @property
    def title(self) -> str:
        return self.win.title
