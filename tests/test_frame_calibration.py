"""Frame calibration tests (headless: fake view + scripted replies)."""

from __future__ import annotations

from PIL import Image

from agb.agent.mock import ScriptedAgent
from agb.loop import LoopResult, _calibrate_frame, _scale_action
from agb.models import Click


def _view(w: int = 400, h: int = 300) -> Image.Image:
    return Image.new("RGB", (w, h), (30, 30, 34))


class TestScaleAction:
    def test_scales_click_coords(self):
        a = _scale_action(Click(x=860, y=660), 2.0, 2.0)
        assert (a.x, a.y) == (430, 330)

    def test_identity_scale_is_noop(self):
        a = _scale_action(Click(x=430, y=330), 1.0, 1.0)
        assert (a.x, a.y) == (430, 330)

    def test_drag_endpoints(self):
        from agb.models import Drag

        a = _scale_action(Drag(x1=100, y1=100, x2=200, y2=200), 2.0, 2.0)
        assert (a.x1, a.y1, a.x2, a.y2) == (50, 50, 100, 100)


class TestCalibrateFrame:
    def test_measures_uniform_scale(self):
        # view 400x300 -> dot at (300, 225); model reports in a 2x frame (600, 450)
        agent = ScriptedAgent(['{"center_x": 600, "center_y": 450}'])
        res = LoopResult(outcome="cap_steps")
        scale = _calibrate_frame(agent, _view(), res)
        assert scale == (2.0, 2.0)
        assert res.model_calls == 1

    def test_pair_reply_in_both_fields(self):
        # observed Ollama behavior: the point pair lands in both fields
        agent = ScriptedAgent(['{"center_x": [600, 450], "center_y": [600, 450]}'])
        res = LoopResult(outcome="cap_steps")
        scale = _calibrate_frame(agent, _view(), res)
        assert scale == (2.0, 2.0)

    def test_near_identity_snaps_to_one(self):
        # 1.03x is within the snap threshold -> treated as our own frame
        agent = ScriptedAgent(['{"center_x": 309, "center_y": 231}'])
        res = LoopResult(outcome="cap_steps")
        scale = _calibrate_frame(agent, _view(), res)
        assert scale == (1.0, 1.0)

    def test_unparsable_reply_falls_back_to_identity(self):
        agent = ScriptedAgent(["I see the dot somewhere!"])
        res = LoopResult(outcome="cap_steps")
        scale = _calibrate_frame(agent, _view(), res)
        assert scale == (1.0, 1.0)
        assert res.errors and "calibration" in res.errors[0]

    def test_extreme_scale_is_clamped(self):
        agent = ScriptedAgent(['{"center_x": 100000, "center_y": 100000}'])
        res = LoopResult(outcome="cap_steps")
        scale = _calibrate_frame(agent, _view(), res)
        assert scale == (3.0, 3.0)
