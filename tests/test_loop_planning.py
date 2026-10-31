"""Loop planning integration tests (headless): plan injection + replan counting."""

from __future__ import annotations

from tests.conftest import ROOT
from tests.fakes import FakeCapture, KillNever

from agb.agent.mock import ScriptedAgent
from agb.inputs import WindowInput
from agb.loop import execute
from agb.models import Click, Done, load_task_spec
from agb.planner import Plan

SQUARE_CENTER = (430, 330)


def _task():
    return load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")


PLAN = Plan(subgoals=[
    {"text": "move to the red square", "check": "cursor over red pixels"},
    {"text": "click it", "check": "hit counter increments"},
])


class PromptCapturingAgent(ScriptedAgent):
    """Records the user prompts it receives."""

    def __init__(self, script):
        super().__init__(script)
        self.prompts: list[str] = []

    def decide(self, system, user, images):
        self.prompts.append(user)
        return super().decide(system, user, images)


class TestPlanInjection:
    def test_plan_in_every_prompt(self):
        agent = PromptCapturingAgent([
            [Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])],
            [Done(claim="clicked")],
        ])
        cap = FakeCapture()
        execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                plan=PLAN, settle_ms=1)
        assert agent.prompts, "no prompts received"
        assert all("PLAN (do these in order)" in p for p in agent.prompts)
        assert all("move to the red square" in p for p in agent.prompts)

    def test_no_plan_no_plan_section(self):
        agent = PromptCapturingAgent([[Done(claim="x")]])
        cap = FakeCapture()
        execute(_task(), agent, cap, WindowInput(cap), KillNever(), settle_ms=1)
        assert agent.prompts and "PLAN (do these in order)" not in agent.prompts[0]


class TestReplan:
    def test_stuck_event_triggers_replan_once(self):
        """Repeated no-op clicks fire stuck detection; the replan runs (throttled)."""
        replans = []

        def replan_fn(progress):
            replans.append(list(progress))
            return Plan(subgoals=[{"text": "try a different spot", "check": "screen changes"}])

        # 12 identical background clicks -> stuck fires at ~5, 10 -> throttled to 1-2 replans
        agent = PromptCapturingAgent([[Click(x=10, y=550)] for _ in range(12)])
        cap = FakeCapture()
        res = execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                      plan=PLAN, replan_fn=replan_fn, max_steps=12,
                      stuck_patience=5, settle_ms=1)
        assert res.stuck_events >= 1
        assert res.replans >= 1
        assert res.replans <= 2  # throttled by _REPLAN_MIN_STEPS
        assert replans and "click" in replans[0][-1]

    def test_replan_none_keeps_old_plan(self):
        replan_calls = []

        def replan_fn(progress):
            replan_calls.append(1)
            return None  # planner failed

        agent = PromptCapturingAgent([[Click(x=10, y=550)] for _ in range(7)])
        cap = FakeCapture()
        res = execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                      plan=PLAN, replan_fn=replan_fn, max_steps=7,
                      stuck_patience=5, settle_ms=1)
        assert replan_calls == [1]
        assert res.replans == 0  # nothing replaced the plan
