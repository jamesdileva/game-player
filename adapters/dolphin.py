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
    "This game is controlled with KEYBOARD only: arrow keys move/aim, "
    "X = confirm/attack, Z = cancel/back, Enter = start/pause. "
    "Do not use CLICK - mouse clicks do nothing."
)


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
