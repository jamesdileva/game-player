"""OSRS adapter: first real game (Sprint 5).

Old School RuneScape is an online MMO — a manual game:
- The HUMAN launches the client and logs in (the agent never touches
  credentials, per AGENTS.md safety rules).
- There is no deterministic title state to read; judging rides on the VLM
  judge plus human labels (agb label), calibrated in Sprint 4.
- The throwaway account accepts the ban risk; kill switch armed every session.

Window title: the official client is "RuneScape"; RuneLite is "RuneLite".
Override with `agb run --window-title` if needed. Recommend the windowed
FIXED layout for stable UI regions.
"""

from __future__ import annotations

from typing import Any

from agb.models import TaskSpec

WINDOW_TITLE = "RuneScape"


def launch() -> None:
    raise RuntimeError(
        "OSRS is a manual game: launch the client and log in yourself "
        "(see tasks/osrs/START_STATE.md), then run without --launch."
    )


def close_all() -> None:
    """Never close the user's logged-in client — a deliberate no-op."""


def read_state(title: str) -> dict[str, Any]:
    """No deterministic window-title state exists for an MMO."""
    return {"stage": None, "note": "manual game; use the VLM judge + human labels"}


def check_success(task: TaskSpec, state: dict[str, Any]) -> bool:
    """No deterministic ground truth; success is decided by the judge + labels."""
    return False


def verify(task: TaskSpec, state: dict[str, Any]) -> dict[str, Any] | None:
    """No cheap deterministic check for an MMO in v1 (chat/XP OCR is future work)."""
    return None
