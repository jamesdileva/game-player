"""Planner tests (headless)."""

from __future__ import annotations

from agb.agent.mock import ScriptedAgent
from agb.planner import make_plan, replan

PLAN_JSON = ('{"subgoals": ['
             '{"text": "move to the square", "check": "cursor over red pixels"}, '
             '{"text": "left-click", "check": "hit counter increments"}]}')


class TestMakePlan:
    def test_happy_path(self, tmp_path):
        agent = ScriptedAgent([PLAN_JSON])
        plan, usage, seconds = make_plan("Click the square.", "brief text", agent, tmp_path)
        assert plan is not None and len(plan.subgoals) == 2
        assert plan.subgoals[1]["check"] == "hit counter increments"
        assert "1. move to the square" in plan.render()
        assert (tmp_path / "plan.md").exists()
        assert "move to the square" in (tmp_path / "plan.md").read_text(encoding="utf-8")

    def test_reask_on_garbage(self, tmp_path):
        agent = ScriptedAgent(["I will think about it...", PLAN_JSON])
        plan, usage, _ = make_plan("g", "b", agent, tmp_path)
        assert plan is not None and len(plan.subgoals) == 2
        assert usage["in_tokens"] >= 0

    def test_total_failure_returns_none(self, tmp_path):
        agent = ScriptedAgent(["nope", "still nope"])
        plan, usage, _ = make_plan("g", "b", agent, tmp_path)
        assert plan is None
        md = (tmp_path / "plan.md").read_text(encoding="utf-8")
        assert "improvise" in md  # plan.md documents the failure

    def test_string_subgoals_tolerated(self, tmp_path):
        raw = '{"subgoals": ["click the square", "click the door"]}'
        agent = ScriptedAgent([raw])
        plan, _, _ = make_plan("g", "b", agent, tmp_path)
        assert plan is not None
        assert plan.subgoals[0]["check"] == "observable change"


class TestReplan:
    def test_revised_plan_written(self, tmp_path):
        agent = ScriptedAgent([PLAN_JSON])
        plan, _, _ = make_plan("g", "b", agent, tmp_path)
        agent2 = ScriptedAgent(
            ['{"subgoals": [{"text": "try the door", "check": "door visible"}]}']
        )
        new, usage, _ = replan("g", "b", plan, ["clicked wrong spot x5"], agent2, tmp_path)
        assert new is not None and new.subgoals[0]["text"] == "try the door"
        md = (tmp_path / "plan.md").read_text(encoding="utf-8")
        assert "revised" in md.lower()
