"""Orchestrator + cost-cap tests.

Headless: cost cap via a charging agent on a fake capture (no window, no mouse).
UI: full run-folder contract (steps.jsonl, frames, replay, mp4) + crash safety.
"""

from __future__ import annotations

import json

import pytest
from tests.conftest import ROOT
from tests.fakes import FakeCapture, KillNever

from agb.agent.mock import ScriptedAgent
from agb.capture import ensure_foreground
from agb.inputs import WindowInput
from agb.killswitch import KillSwitch
from agb.loop import execute
from agb.models import Click, Done, Wait, load_task_spec
from agb.orchestrator import make_run_dir
from agb.orchestrator import run as run_orchestrated
from agb.recorder import Recorder

SQUARE_CENTER = (430, 330)


class ChargingAgent(ScriptedAgent):
    """Scripted agent whose every call costs money."""

    def decide(self, system, user, images):
        d = super().decide(system, user, images)
        d.usage["cost_usd"] = 0.10
        return d


def _task(name: str):
    return load_task_spec(ROOT / "tasks" / "testbed" / f"{name}.yaml")


class TestCostCap:
    def test_cap_cost_stops_the_loop(self):
        """Exit criterion 2: the cost cap produces the correct outcome."""
        spec = _task("click-the-red-square")
        agent = ChargingAgent([[Wait(ms=1)]] * 10)
        cap = FakeCapture()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(),
                      max_cost_usd=0.25, settle_ms=1)
        assert res.outcome == "cap_cost"
        assert res.steps == 3
        assert res.cost_usd == pytest.approx(0.30)

    def test_zero_cost_cap_is_never_enforced(self):
        spec = _task("click-the-red-square")
        agent = ScriptedAgent([[Done(claim="free")]])
        cap = FakeCapture()
        res = execute(spec, agent, cap, WindowInput(cap), KillNever(), settle_ms=1)
        assert res.outcome == "claimed_done"


class TestOrchestratorRun:
    pytestmark = pytest.mark.ui

    def test_run_folder_contract(self, tmp_path, fakegame):
        """Exit criterion 1: a run is replayable from its folder alone."""
        ensure_foreground(fakegame)
        import time as _t

        _t.sleep(0.3)
        from agb.capture import WindowCapture

        cap = WindowCapture("FakeGame")
        agent = ScriptedAgent(
            [[Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])], [Done(claim="clicked")]]
        )
        record = run_orchestrated(
            _task("click-the-red-square"), agent, cap, KillSwitch(),
            tmp_path, view_max=(640, 480),
        )
        run_dir = tmp_path / record["run_id"]
        assert record["success"] is True
        assert (run_dir / "result.json").exists()
        assert (run_dir / "replay.html").exists()
        assert (run_dir / "run.mp4").exists()
        assert (run_dir / "run.mp4").stat().st_size > 1000
        lines = (run_dir / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
        recs = [json.loads(line) for line in lines]
        assert len(recs) >= 2
        assert all(r.get("frame") for r in recs)
        assert (run_dir / recs[0]["frame"]).exists()
        assert any(r.get("raw_reply") for r in recs)  # raw replies recorded for debugging
        html = (run_dir / "replay.html").read_text(encoding="utf-8")
        assert recs[0]["frame"] in html

    def test_crash_mid_run_leaves_partial_logs(self, tmp_path):
        """Exit criterion 3: a crash still leaves usable partial logs."""
        spec = _task("click-the-red-square")
        run_dir = make_run_dir(tmp_path, spec, "scripted-mock")
        rec = Recorder(run_dir)

        class CrashingAgent(ScriptedAgent):
            def decide(self, system, user, images):
                if len(self._script) <= 1:  # crash after the first scripted step
                    raise KeyboardInterrupt("simulated crash")
                return super().decide(system, user, images)

        agent = CrashingAgent([[Wait(ms=1)], [Wait(ms=1)]])
        cap = FakeCapture()
        with pytest.raises(KeyboardInterrupt):
            execute(spec, agent, cap, WindowInput(cap), KillNever(),
                    recorder=rec, settle_ms=1)
        rec.close()

        lines = (run_dir / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
        recs = [json.loads(line) for line in lines]
        assert recs and recs[0]["step"] == 0
