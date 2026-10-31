"""Loop orchestration tests on the real fake game window (marked `ui`).

Uses the ScriptedAgent so no API tokens are burned (AGENTS.md).
"""

from __future__ import annotations

import threading
import time

import pytest
from adapters import get_adapter
from tests.conftest import ROOT

from agb.agent.mock import ScriptedAgent
from agb.capture import WindowCapture, ensure_foreground
from agb.inputs import WindowInput
from agb.killswitch import KillSwitch
from agb.loop import execute
from agb.models import Click, Done, Scroll, load_task_spec

pytestmark = pytest.mark.ui

SQUARE_CENTER = (430, 330)  # window 800x600, square at (400,300) size 60
DOOR_CENTER = (100, 140)  # door rect (60, 60, 80, 160)
SCALE_1_0 = 1.0  # 800x600 window, capture cap 1280x720


def _task(name: str):
    return load_task_spec(ROOT / "tasks" / "testbed" / f"{name}.yaml")


@pytest.fixture
def harness(fakegame):
    """Capture + input + kill switch wired to the running fake game."""
    ensure_foreground(fakegame)
    time.sleep(0.3)
    cap = WindowCapture("FakeGame")
    return fakegame, cap, WindowInput(cap), KillSwitch()


def test_mock_completes_square_task(harness):
    win, cap, inp, kill = harness
    agent = ScriptedAgent(
        [[Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])], [Done(claim="clicked")]]
    )
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill, max_steps=5)

    assert result.outcome == "claimed_done"
    assert result.invalid_outputs == 0
    state = get_adapter("fakegame").read_state(win.title)
    assert get_adapter("fakegame").check_success(_task("click-the-red-square"), state)
    assert state["hits"] >= 1


def test_mock_completes_door_task(harness):
    win, cap, inp, kill = harness
    agent = ScriptedAgent(
        [[Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1])] for _ in range(3)]
        + [[Click(x=DOOR_CENTER[0], y=DOOR_CENTER[1])], [Done(claim="door")]]
    )
    result = execute(_task("reach-the-door"), agent, cap, inp, kill, max_steps=10)

    assert result.outcome == "claimed_done"
    state = get_adapter("fakegame").read_state(win.title)
    assert get_adapter("fakegame").check_success(_task("reach-the-door"), state)
    assert state["stage"] >= 3


def test_never_finishing_agent_hits_step_cap_cleanly(harness):
    """Exit criterion 3: failed runs terminate cleanly (cap), never hang."""
    _win, cap, inp, kill = harness
    agent = ScriptedAgent([])  # always waits
    t0 = time.perf_counter()
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill,
                     max_steps=4, settle_ms=50)
    elapsed = time.perf_counter() - t0

    assert result.outcome == "cap_steps"
    assert result.steps == 4
    assert elapsed < 30  # bounded, not hung


def test_kill_switch_aborts_running_loop(harness):
    """Exit criterion 3: kill switch stops a running loop."""
    _win, cap, inp, _kill_unused = harness
    kill = KillSwitch()
    agent = ScriptedAgent([])  # would run forever

    threading.Timer(0.5, kill.event.set).start()
    t0 = time.perf_counter()
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill,
                     max_steps=100, settle_ms=100)

    assert result.outcome == "aborted"
    assert time.perf_counter() - t0 < 10


def test_invalid_output_counted_and_reasked(harness):
    """Exit criterion 2: invalid-output rate is counted; one re-ask happens."""
    _win, cap, inp, kill = harness
    agent = ScriptedAgent(
        [
            "this is not json at all",
            [Click(x=SQUARE_CENTER[0], y=SQUARE_CENTER[1]), Done(claim="ok")],
        ]
    )
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill, max_steps=5)

    assert result.invalid_outputs == 1
    assert result.model_calls == 2  # original + one re-ask
    assert result.invalid_rate == 0.5
    assert result.outcome == "claimed_done"
    assert result.errors and "no_json" in result.errors[0]


def test_unsupported_action_counted_not_fatal(harness):
    _win, cap, inp, kill = harness
    agent = ScriptedAgent([[Scroll(x=10, y=10, dy=-3)], [Done(claim="scrolled")]])
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill, max_steps=5)

    assert result.invalid_actions == 1
    assert result.outcome == "claimed_done"
    # the done claim is not evidence: nothing was clicked, so success stays False
    state = get_adapter("fakegame").read_state(_win.title)
    assert get_adapter("fakegame").check_success(_task("click-the-red-square"), state) is False
    assert state["hits"] == 0


def test_stuck_hint_fires_after_repeated_noop_clicks(harness):
    """Clicking the same empty spot repeatedly must raise stuck events."""
    win, cap, inp, kill = harness
    agent = ScriptedAgent([[Click(x=10, y=550)] for _ in range(8)])
    result = execute(_task("click-the-red-square"), agent, cap, inp, kill,
                     max_steps=8, settle_ms=50)

    assert result.stuck_events >= 1
    state = get_adapter("fakegame").read_state(win.title)
    assert state["hits"] == 0  # clicks landed on the background
