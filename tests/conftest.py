"""Shared fixtures and process-wide setup for tests."""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Physical-pixel coordinates everywhere, before any window code runs (guide 15).
from agb.config import ensure_dpi_awareness  # noqa: E402

ensure_dpi_awareness()

# Make `testbed.*` importable (repo root on sys.path).
sys.path.insert(0, str(ROOT))


def _windows_matching(title_substring: str):
    import pygetwindow as gw

    return [
        w
        for w in gw.getAllWindows()
        if title_substring.lower() in (w.title or "").lower() and w.width > 0
    ]


def wait_for_window(title_substring: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = _windows_matching(title_substring)
        if matches:
            return matches[0]
        time.sleep(0.2)
    raise TimeoutError(f"Window {title_substring!r} did not appear within {timeout}s")


def wait_until_gone(title_substring: str, timeout: float = 5.0) -> None:
    """Windows can linger in the enumeration briefly after their process dies."""
    deadline = time.time() + timeout
    while time.time() < deadline and _windows_matching(title_substring):
        time.sleep(0.1)


@contextmanager
def spawn_fakegame(size: str = "800x600", square: str = "400,300", hits: int = 3):
    """Runs the fake game in a subprocess; yields its pygetwindow handle."""
    wait_until_gone("FakeGame")  # never match a window from a previous test
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "testbed" / "fakegame.py"),
            "--size", size,
            "--square", square,
            "--hits", str(hits),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        win = wait_for_window("FakeGame")
        time.sleep(0.8)  # let the first frame render
        yield win
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        wait_until_gone("FakeGame")


@pytest.fixture
def fakegame():
    with spawn_fakegame() as win:
        yield win


@pytest.fixture
def spawn():
    return spawn_fakegame
