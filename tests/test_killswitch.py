"""Kill switch tests.

pynput's GlobalHotKeys ignores injected (synthetic) key events by design, so
the full OS-hook chain can only be verified with a physical key press — that
is the pre-session manual check in AGENTS.md. These tests verify everything
verifiable in software: the combination is registered, the matching logic
fires, the listener is alive, and a trip halts an action loop within 1 second
(the Sprint 0 exit criterion).
"""

from __future__ import annotations

import threading
import time

import pytest
from pynput import keyboard

from agb.killswitch import DEFAULT_COMBO, KillSwitch

pytestmark = pytest.mark.ui


def _canonicalizer():
    # Listener instance used only for canonical(); never started.
    return keyboard.Listener()


class TestWiring:
    def test_hotkey_combination_registered(self):
        keys = keyboard.HotKey.parse(DEFAULT_COMBO)
        assert len(keys) == 3
        canon = [_canonicalizer().canonical(k) for k in keys]
        chars = {getattr(k, "char", None) for k in canon}
        names = {getattr(k, "name", "") for k in canon}
        assert "q" in chars
        assert {"ctrl", "alt"} <= names

    def test_hotkey_logic_fires_callback(self):
        fired = threading.Event()
        hk = keyboard.HotKey(keyboard.HotKey.parse(DEFAULT_COMBO), fired.set)
        canon = _canonicalizer().canonical
        for k in (keyboard.Key.ctrl, keyboard.Key.alt, keyboard.KeyCode(char="q")):
            hk.press(canon(k))
        assert fired.is_set()

    def test_listener_starts_alive_and_not_tripped(self):
        ks = KillSwitch()
        time.sleep(0.2)
        assert ks.armed
        assert not ks.tripped


class TestTripResponse:
    def test_trip_halts_action_loop_within_1s(self):
        """Exit criterion 3: the kill switch stops a running script within 1 second."""
        kill = KillSwitch()
        time.sleep(0.2)

        threading.Timer(0.3, kill.event.set).start()  # as the OS hook would

        steps = 0
        t0 = time.perf_counter()
        while not kill.tripped:
            steps += 1  # an action batch would execute here
            time.sleep(0.01)
        elapsed = time.perf_counter() - t0
        assert steps > 0
        assert elapsed <= 1.0, f"loop took {elapsed:.3f}s to halt (> 1s)"
