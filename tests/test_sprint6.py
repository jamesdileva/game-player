"""Sprint 6 tests: paused mode, stuck budget, dolphin adapter (headless)."""

from __future__ import annotations

import subprocess
import sys

import psutil
import pytest
from tests.conftest import ROOT
from tests.fakes import FakeCapture, KillNever

from agb.agent.mock import ScriptedAgent
from agb.inputs import WindowInput
from agb.loop import execute
from agb.models import Click, Done, load_task_spec
from agb.pause import GamePauser

SQUARE_CENTER = (430, 330)


def _task(name: str):
    return load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")


class CountingPauser:
    """Fake pauser: tracks net suspend state (idempotent like the real one)."""

    def __init__(self):
        self.suspends = 0
        self.resumes = 0
        self.on = False

    def suspend(self):
        self.suspends += 1
        self.on = True

    def resume(self):
        self.resumes += 1
        self.on = False


class TestGamePauser:
    def test_suspend_resume_on_real_process(self):
        """psutil suspend/resume works end-to-end on a spawned process."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        try:
            pauser = GamePauser(proc.pid)
            with pauser:
                assert psutil.Process(proc.pid).status() == psutil.STATUS_STOPPED
            assert psutil.Process(proc.pid).status() != psutil.STATUS_STOPPED
        finally:
            proc.kill()

    def test_missing_process_is_tolerated(self):
        pauser = GamePauser(pid=999999999)
        pauser.suspend()  # NoSuchProcess swallowed
        pauser.resume()


class TestPausedMode:
    def test_paused_mode_suspends_around_every_call(self):
        """time_mode=paused wraps every model call in suspend/resume."""
        spec = _task("click-the-red-square")
        spec.loop.time_mode = "paused"
        agent = ScriptedAgent([[Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])], [Done(claim="x")]])
        cap = FakeCapture()
        pauser = CountingPauser()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      pauser=pauser, settle_ms=1)
        assert res.outcome == "claimed_done"
        # frozen during decide, resumed for the action phase, never left frozen
        assert pauser.on is False
        assert pauser.suspends >= 2 and pauser.resumes >= 1

    def test_realtime_never_suspends(self):
        spec = _task("click-the-red-square")
        agent = ScriptedAgent([[Done(claim="x")]])
        cap = FakeCapture()
        pauser = CountingPauser()
        execute(spec, agent, cap, WindowInput(cap), KillNever(), pauser=pauser, settle_ms=1)
        assert pauser.suspends == 0

    def test_pauser_resumes_on_model_failure(self):
        """A crashing model call must never leave the game suspended."""
        spec = _task("click-the-red-square")

        class CrashingAgent(ScriptedAgent):
            def decide(self, system, user, images):
                raise RuntimeError("boom")

        cap = FakeCapture()
        pauser = CountingPauser()
        res = execute(spec, CrashingAgent([]), cap, WindowInput(cap), KillNever(),
                      pauser=pauser, max_steps=3, settle_ms=1)
        assert res.outcome == "model_error"
        assert pauser.suspends == pauser.resumes  # resumed every time


class TestStuckBudget:
    def test_stuck_budget_caps_the_run(self):
        """Exit criterion: repeated stuck events produce cap_stuck."""
        spec = _task("click-the-red-square")
        spec.loop.max_stuck_events = 1
        agent = ScriptedAgent([[Click(x=10, y=550)] for _ in range(10)])
        cap = FakeCapture()  # solid color: nothing ever changes
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      max_steps=10, stuck_patience=3, settle_ms=1)
        assert res.outcome == "cap_stuck"
        assert res.stuck_events >= 1

    def test_zero_stuck_budget_disables_it(self):
        spec = _task("click-the-red-square")
        spec.loop.max_stuck_events = 0
        agent = ScriptedAgent([[Click(x=10, y=550)] for _ in range(10)])
        cap = FakeCapture()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      max_steps=10, stuck_patience=2, settle_ms=1)
        assert res.outcome == "cap_steps"  # stuck events happen but never cap
        assert res.stuck_events >= 1


class TestDolphinAdapter:
    def test_registry_maps_tos_melee_dolphin(self):
        from adapters import get_adapter

        for game in ("tos", "melee", "dolphin"):
            assert get_adapter(game).WINDOW_TITLE == "Dolphin"

    def test_launch_raises_manual_error(self):
        from adapters import get_adapter

        with pytest.raises(RuntimeError, match="manual game"):
            get_adapter("tos").launch()

    def test_no_deterministic_state(self):
        from adapters import get_adapter

        adapter = get_adapter("tos")
        spec = load_task_spec(ROOT / "tasks" / "tos" / "first-battle.yaml")
        assert adapter.verify(spec, {"stage": None}) is None
        assert adapter.check_success(spec, {"stage": None}) is False


class TestTaskSpecs:
    def test_tos_tasks_parse(self):
        menu = load_task_spec(ROOT / "tasks" / "tos" / "menu-nav.yaml")
        battle = load_task_spec(ROOT / "tasks" / "tos" / "first-battle.yaml")
        stretch = load_task_spec(ROOT / "tasks" / "melee" / "cpu-stretch.yaml")
        assert menu.loop.assist_level == "L2" and menu.loop.time_mode == "realtime"
        assert battle.loop.time_mode == "paused"
        assert battle.success.milestones  # milestone partial credit present
        assert stretch.tier == 4 and stretch.loop.time_mode == "paused"


class TestKeysOnly:
    def test_pointer_actions_rejected_in_keys_only_mode(self):
        spec = _task("click-the-red-square")
        agent = ScriptedAgent([[Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])], [Done(claim="x")]])
        cap = FakeCapture()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      keys_only=True, settle_ms=1)
        # the click is rejected (counted), the done still completes the run
        assert res.invalid_actions >= 1
        assert res.outcome == "claimed_done"

    def test_keys_still_work_in_keys_only_mode(self):
        from agb.models import Key

        spec = _task("click-the-red-square")
        agent = ScriptedAgent([[Key(key="x")], [Done(claim="x")]])
        cap = FakeCapture()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      keys_only=True, settle_ms=1)
        assert res.invalid_actions == 0
        assert res.outcome == "claimed_done"

    def test_controls_hint_in_prompt(self):
        from tests.test_loop_planning import PromptCapturingAgent  # type: ignore

        spec = _task("click-the-red-square")
        agent = PromptCapturingAgent([[Done(claim="x")]])
        cap = FakeCapture()
        execute(spec, agent, cap, WindowInput(cap), KillNever(),
                keys_only=True, controls_hint="arrows + X", settle_ms=1)
        assert agent.prompts and "keyboard only" in agent.prompts[0]
        assert "CONTROLS: arrows + X" in agent.prompts[0]
