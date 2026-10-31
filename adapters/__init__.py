"""Per-game adapters.

Game-specific knowledge (window titles, launch commands, OCR regions,
deterministic checks) lives here, never in `src/agb` core modules.
"""

from __future__ import annotations

from typing import Any, Protocol


class GameAdapter(Protocol):
    WINDOW_TITLE: str

    def launch(self) -> None: ...

    def read_state(self, title: str) -> dict[str, Any]: ...

    def check_success(self, task, state: dict[str, Any]) -> bool: ...


def get_adapter(game: str) -> GameAdapter:
    if game == "fakegame":
        from . import fakegame

        return fakegame
    raise KeyError(
        f"No adapter for game {game!r}. Add one under adapters/ for new games."
    )
