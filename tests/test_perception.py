"""Perception assist tests (headless)."""

from __future__ import annotations

import io

from PIL import Image
from tests.conftest import ROOT
from tests.fakes import FakeCapture, KillNever

from agb.agent.base import Decision
from agb.loop import execute
from agb.models import load_task_spec
from agb.perception import apply_assist, grid_overlay


class TestGridOverlay:
    def test_draws_yellow_lines(self):
        img = Image.new("RGB", (200, 200), (0, 0, 0))
        out = grid_overlay(img, step=80)
        # a vertical line pixel at x=80 must be yellow
        assert out.getpixel((80, 100)) == (255, 255, 0)
        assert out.getpixel((100, 80)) == (255, 255, 0)
        # original untouched
        assert img.getpixel((80, 100)) == (0, 0, 0)

    def test_apply_assist_l0_is_identity(self):
        img = Image.new("RGB", (100, 100), (1, 2, 3))
        assert apply_assist(img, "L0") is img

    def test_apply_assist_l1_grids(self):
        img = Image.new("RGB", (200, 200), (0, 0, 0))
        out = apply_assist(img, "L1")
        assert out.getpixel((80, 100)) == (255, 255, 0)


class CapturingAgent:
    """Records the images it receives; returns done immediately."""

    name = "capturing-mock"

    def __init__(self):
        self.received: list[bytes] = []

    def decide(self, system, user, images):
        self.received.extend(images)
        return Decision(raw='{"thought": "t", "actions": [{"type": "done"}]}',
                        usage={"in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0, "latency_ms": 0})


def _task(assist: str):
    spec = load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")
    spec.loop.assist_level = assist
    return spec


class TestLoopAssistWiring:
    def test_l1_agent_sees_grid_recorder_keeps_clean(self, tmp_path):
        agent = CapturingAgent()
        from agb.inputs import WindowInput
        from agb.recorder import Recorder

        rec = Recorder(tmp_path)
        execute(_task("L1"), agent, FakeCapture(), WindowInput(FakeCapture()),
                KillNever(), recorder=rec, settle_ms=1)
        rec.close()
        assert agent.received, "agent received no images"
        img = Image.open(io.BytesIO(agent.received[0]))
        # 640x480 view with step-80 grid: yellow line at x=80 (JPEG shifts the hue)
        px = img.getpixel((80, 100))
        assert px[0] > 200 and px[1] > 200 and px[2] < 180, f"expected grid yellow, got {px}"
        # recorded frame is the CLEAN view (no yellow grid; JPEG noise tolerated)
        rec0 = Image.open(tmp_path / "frames" / "000000.jpg")
        for px in rec0.getdata():
            assert not (px[0] > 200 and px[1] > 200 and px[2] < 100), "grid leaked into recording"

    def test_l0_agent_sees_clean(self):
        agent = CapturingAgent()
        from agb.inputs import WindowInput

        execute(_task("L0"), agent, FakeCapture(), WindowInput(FakeCapture()),
                KillNever(), settle_ms=1)
        assert agent.received
        img = Image.open(io.BytesIO(agent.received[0]))
        colors = img.getcolors(maxcolors=8)
        assert colors and len(colors) == 1  # no grid drawn
