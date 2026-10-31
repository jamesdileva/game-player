"""Fake-game adapter: window title, launch, deterministic state from the title.

The fake game mirrors its progress in the window title
(``FakeGame | stage N | hits k/M``), which gives demo runs deterministic
ground truth without a judge. Real judging (VLM + adapters feeding it)
arrives in Sprint 4; these checks are the first "adapter verifier" pattern.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agb.models import TaskSpec

ROOT = Path(__file__).resolve().parents[1]
WINDOW_TITLE = "FakeGame"

_TITLE_RE = re.compile(r"stage (\d+) \| hits (\d+)/(\d+)")


def start_command() -> list[str]:
    return [sys.executable, str(ROOT / "testbed" / "fakegame.py")]


def launch() -> subprocess.Popen:
    """Start a fresh fake game; the caller owns the returned process."""
    return subprocess.Popen(
        start_command(),
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def close_all() -> None:
    """Close any leftover fake game windows so runs start from a clean state."""
    import pygetwindow as gw

    for w in gw.getAllWindows():
        if WINDOW_TITLE.lower() in (w.title or "").lower():
            try:
                w.close()
            except Exception:
                pass
    deadline = time.time() + 5
    while time.time() < deadline:
        if not any(
            WINDOW_TITLE.lower() in (w.title or "").lower() for w in gw.getAllWindows()
        ):
            return
        time.sleep(0.1)


def read_state(title: str) -> dict[str, Any]:
    m = _TITLE_RE.search(title)
    if not m:
        return {"stage": None, "hits": None, "hits_needed": None, "complete": False}
    stage, hits, needed = (int(g) for g in m.groups())
    return {
        "stage": stage,
        "hits": hits,
        "hits_needed": needed,
        "complete": stage >= 4,
    }


def check_success(task: TaskSpec, state: dict[str, Any]) -> bool:
    """Deterministic per-task ground truth (testbed only)."""
    if task.id == "testbed-click-red-square-001":
        return (state["hits"] or 0) >= 1
    if task.id == "testbed-reach-door-001":
        return (state["stage"] or 0) >= 3
    return False
