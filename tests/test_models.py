"""Contract tests: task spec loading and action validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agb.models import parse_actions

ROOT = Path(__file__).resolve().parents[1]


class TestTaskSpec:
    def test_loads_sample_task(self):
        from agb.models import load_task_spec

        spec = load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")
        assert spec.id == "testbed-click-red-square-001"
        assert spec.game == "fakegame"
        assert spec.tier == 1
        assert spec.mode == "study"
        assert spec.success.verifiers == ["scripted"]
        assert spec.research.mode == "none"
        assert spec.loop.time_mode == "realtime"
        assert spec.limits.max_cost_usd == 0.0

    def test_defaults_fill_in(self):
        from agb.models import TaskSpec

        spec = TaskSpec.model_validate(
            {"id": "t", "game": "g", "goal": "do a thing", "success": {"evidence": "visible"}}
        )
        assert spec.tier == 1
        assert spec.mode == "study"
        assert spec.limits.max_steps == 300
        assert spec.limits.max_wall_hours is None
        assert spec.checkpoint_every_steps == 25
        assert spec.loop.assist_level == "L0"
        assert spec.loop.topology == "single"
        assert spec.loop.decision_hz is None

    def test_rejects_bad_tier(self):
        from agb.models import TaskSpec

        with pytest.raises(ValidationError):
            TaskSpec.model_validate(
                {"id": "t", "game": "g", "goal": "x", "tier": 9, "success": {"evidence": "e"}}
            )

    def test_rejects_bad_mode(self):
        from agb.models import TaskSpec

        with pytest.raises(ValidationError):
            TaskSpec.model_validate(
                {
                    "id": "t", "game": "g", "goal": "x",
                    "mode": "speedrun", "success": {"evidence": "e"},
                }
            )

    def test_rejects_missing_evidence(self):
        from agb.models import TaskSpec

        with pytest.raises(ValidationError):
            TaskSpec.model_validate({"id": "t", "game": "g", "goal": "x"})


class TestActions:
    def test_click_valid(self):
        (a,) = parse_actions([{"type": "click", "x": 640, "y": 360}])
        assert a.x == 640
        assert a.button == "left"

    def test_all_types_round_trip(self):
        raw = [
            {"type": "click", "x": 1, "y": 2, "button": "right"},
            {"type": "double_click", "x": 1, "y": 2},
            {"type": "drag", "x1": 1, "y1": 2, "x2": 3, "y2": 4},
            {"type": "move", "x": 1, "y": 2},
            {"type": "key", "key": "w", "hold_ms": 800},
            {"type": "type", "text": "hello"},
            {"type": "scroll", "x": 1, "y": 2, "dy": -3},
            {"type": "wait", "ms": 1000},
            {"type": "note", "text": "scratchpad"},
            {"type": "done", "claim": "I did it."},
        ]
        actions = parse_actions(raw)
        assert [a.type for a in actions] == [r["type"] for r in raw]

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            parse_actions([{"type": "teleport", "x": 1, "y": 2}])

    def test_rejects_missing_coords(self):
        with pytest.raises(ValidationError):
            parse_actions([{"type": "click"}])
