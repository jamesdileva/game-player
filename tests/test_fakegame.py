"""Headless tests of the fake game state machine (no window needed)."""

from __future__ import annotations

from testbed.fakegame import DOOR, ENEMY, FakeGameState


def _center(rect):
    x, y, w, h = rect
    return x + w // 2, y + h // 2


class TestStage1Square:
    def test_hit_inside_increments(self):
        s = FakeGameState(hits_needed=3)
        assert s.register_click(*_center(s.square_rect)) == "hit_square"
        assert s.hits == 1
        assert s.stage == 1

    def test_click_outside_does_nothing(self):
        s = FakeGameState()
        assert s.register_click(5, 550) is None
        assert s.hits == 0

    def test_completes_after_needed_hits(self):
        s = FakeGameState(hits_needed=3)
        for _ in range(3):
            s.register_click(*_center(s.square_rect))
        assert s.stage == 2
        assert s.events[-1] == "stage_door"


class TestStage2Door:
    def test_door_click_advances(self):
        s = FakeGameState(hits_needed=1)
        s.register_click(*_center(s.square_rect))
        assert s.register_click(*_center(DOOR)) == "stage_enemy"
        assert s.stage == 3

    def test_square_click_ignored_in_stage2(self):
        s = FakeGameState(hits_needed=1)
        s.register_click(*_center(s.square_rect))
        assert s.register_click(*_center(s.square_rect)) is None
        assert s.stage == 2


class TestStage3Enemy:
    def test_full_playthrough(self):
        s = FakeGameState(hits_needed=1)
        assert s.register_click(*_center(s.square_rect)) == "stage_door"
        assert s.register_click(*_center(DOOR)) == "stage_enemy"
        assert s.register_click(*_center(ENEMY)) == "complete"
        assert s.stage == 4
        assert s.events == ["stage_door", "stage_enemy", "complete"]
