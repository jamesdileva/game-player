"""Evidence-turn tests (headless): the capped proof phase after a done claim."""

from __future__ import annotations

from tests.conftest import ROOT
from tests.fakes import FakeCapture, KillNever

from agb.agent.mock import ScriptedAgent
from agb.inputs import WindowInput
from agb.loop import execute
from agb.models import Done, Wait, load_task_spec

SQUARE_CENTER = (430, 330)


def _task():
    return load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")


class PromptCapturingAgent(ScriptedAgent):
    def __init__(self, script):
        super().__init__(script)
        self.prompts: list[str] = []

    def decide(self, system, user, images, **kwargs):
        self.prompts.append(user)
        return super().decide(system, user, images)


def test_evidence_turn_runs_after_done_claim():
    agent = PromptCapturingAgent([
        [Wait(ms=1)],
        [Done(claim="I did it")],           # the claim
        [Wait(ms=1)],                        # evidence steps
        [Wait(ms=1)],
        [Wait(ms=1)],
        [Wait(ms=1)],
    ])
    cap = FakeCapture()
    res = execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                  evidence_steps=3, settle_ms=1)
    assert res.outcome == "claimed_done"
    assert res.evidence_steps_used == 3
    evidence_prompts = [p for p in agent.prompts if "EVIDENCE TURN" in p]
    assert len(evidence_prompts) == 3
    assert "show the proof on screen" in evidence_prompts[0]


def test_done_without_evidence_budget_claims_immediately():
    agent = PromptCapturingAgent([[Done(claim="done")], [Wait(ms=1)]])
    cap = FakeCapture()
    res = execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                  evidence_steps=0, settle_ms=1)
    assert res.outcome == "claimed_done"
    assert res.evidence_steps_used == 0


def test_caps_still_apply_during_evidence_turn():
    """The step cap bounds the evidence turn (never hangs)."""
    agent = PromptCapturingAgent([
        [Done(claim="done")],
        *[[Wait(ms=1)] for _ in range(10)],
    ])
    cap = FakeCapture()
    res = execute(_task(), agent, cap, WindowInput(cap), KillNever(),
                  max_steps=3, evidence_steps=3, settle_ms=1)
    assert res.steps == 3
    assert res.outcome == "cap_steps"
