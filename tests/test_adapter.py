"""Fake-game adapter tests (headless: state parsing + success mapping)."""

from __future__ import annotations

import pytest
from adapters import get_adapter
from adapters.fakegame import check_success, read_state

from agb.models import TaskSpec


def _task(task_id: str) -> TaskSpec:
    return TaskSpec.model_validate(
        {"id": task_id, "game": "fakegame", "goal": "g", "success": {"evidence": "e"}}
    )


class TestRegistry:
    def test_fakegame_resolves(self):
        assert get_adapter("fakegame").WINDOW_TITLE == "FakeGame"

    def test_unknown_game_raises(self):
        with pytest.raises(KeyError):
            get_adapter("some-aaa-game")


class TestReadState:
    def test_parses_title(self):
        state = read_state("FakeGame | stage 2 | hits 3/3")
        assert state == {"stage": 2, "hits": 3, "hits_needed": 3, "complete": False}

    def test_complete_stage(self):
        assert read_state("FakeGame | stage 4 | hits 3/3")["complete"] is True

    def test_unparsable_title(self):
        assert read_state("Notepad")["stage"] is None


class TestCheckSuccess:
    def test_square_task(self):
        assert check_success(_task("testbed-click-red-square-001"), {"hits": 1}) is True
        assert check_success(_task("testbed-click-red-square-001"), {"hits": 0}) is False

    def test_door_task(self):
        assert check_success(_task("testbed-reach-door-001"), {"stage": 3}) is True
        assert check_success(_task("testbed-reach-door-001"), {"stage": 2}) is False

    def test_unknown_task_is_never_success(self):
        assert check_success(_task("some-other-task"), {"stage": 4}) is False
