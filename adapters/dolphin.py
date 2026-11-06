"""Dolphin emulator adapter: manual-game semantics (the human drives Dolphin).

Emulators are the account-free breadth path: save states give deterministic
start states, and paused mode is safe (single-player). The human launches
Dolphin with the game and loads the save state; the agent never touches the
emulator UI.

Window title: Dolphin's title contains the game name (e.g. "Dolphin 2503 |
Tales of Symphonia"). Override with `agb run --window-title`.
"""

from __future__ import annotations

from typing import Any

from agb.models import TaskSpec

WINDOW_TITLE = "Dolphin"
KEYS_ONLY = True  # the GCN pad is keyboard-mapped; mouse clicks do nothing in-game
CONTROLS_HINT = (
    "Keyboard mapping for this game: the X key is the game's A button "
    "(confirm/attack) - to press A, send KEY x. The Z key is the game's "
    "B button (cancel/back) - send KEY z. The Enter key is Start - send "
    "KEY enter. Arrow keys move the cursor/character. "
    "Do not use CLICK - mouse clicks do nothing."
)
# dialect translation: models speak GameCube (KEY a = the A button);
# this maps their intent onto the keyboard bindings above
KEY_MAP = {"a": "x", "b": "z", "start": "enter"}


def launch() -> None:
    raise RuntimeError(
        "Dolphin is a manual game: launch Dolphin with the game and load your "
        "save state yourself, then run without --launch."
    )


def close_all() -> None:
    """Never close the user's emulator — a deliberate no-op."""


def read_state(title: str) -> dict[str, Any]:
    return {"stage": None, "note": "manual emulator; use the VLM judge + human labels"}


def check_success(task: TaskSpec, state: dict[str, Any]) -> bool:
    return False


def verify(task: TaskSpec, state: dict[str, Any]) -> dict[str, Any] | None:
    return None
