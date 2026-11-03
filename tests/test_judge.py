"""Judge tests (headless): keyframes, strictness, verdict parsing, double-run."""

from __future__ import annotations

from PIL import Image

from agb.judge import Verdict, _parse_verdict, judge_run, select_keyframes
from agb.models import TaskSpec
from agb.recorder import Recorder

SUCCESS_JSON = ('{"verdict": "success", "confidence": 0.9, '
                '"cited_frames": ["000004.jpg"], "reasoning": "counter visible", '
                '"milestones": {"square clicked": true}}')
FAIL_JSON = '{"verdict": "fail", "confidence": 0.8, "cited_frames": [], "reasoning": "no evidence"}'


def _spec(**overrides) -> TaskSpec:
    data = {"id": "t", "game": "fakegame", "goal": "click the square",
            "success": {"evidence": "hit counter increments", "evidence_step": "show the title"}}
    data["success"].update(overrides)
    return TaskSpec.model_validate(data)


class MockJudge:
    """Returns canned replies in order; records the images and prompt it got."""

    name = "mock-judge"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.image_counts: list[int] = []

    def decide(self, system, user, images):
        self.prompts.append(system + "\n" + user)
        self.image_counts.append(len(images))
        return Decision(self.replies.pop(0) if self.replies else FAIL_JSON,
                        {"in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0, "latency_ms": 0})


from agb.agent.base import Decision  # noqa: E402


def _recorded_run(tmp_path, n_steps: int = 6):
    rec = Recorder(tmp_path)
    for i in range(n_steps):
        rec.log_step({"phase": "execute", "thought": f"t{i}", "actions": [],
                      "usage": {}, "raw_reply": f"SECRET-THOUGHT-{i}", "error": None},
                     Image.new("RGB", (40, 30), (i * 30, 10, 10)))
    rec.close()
    return tmp_path


class TestSelectKeyframes:
    def test_baseline_plus_tail_plus_sample(self, tmp_path):
        _recorded_run(tmp_path, n_steps=10)
        (tmp_path / "baseline.jpg").write_bytes(b"fake")
        # make baseline a real image (judge reads bytes)
        Image.new("RGB", (10, 10)).save(tmp_path / "baseline.jpg")
        frames = select_keyframes(tmp_path, max_frames=8)
        assert len(frames) <= 8
        assert frames[0].name == "baseline.jpg"
        assert frames[-1].name == "000009.jpg"  # claim/evidence tail

    def test_no_frames(self, tmp_path):
        assert select_keyframes(tmp_path) == []


class TestStrictness:
    def test_judge_never_sees_agent_thoughts(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=3)
        judge = MockJudge([SUCCESS_JSON])
        judge_run(run_dir, _spec(), judge)
        for p in judge.prompts:
            assert "SECRET-THOUGHT" not in p  # raw replies never leak
            assert "hit counter increments" in p  # task evidence does


class TestParseVerdict:
    def test_valid(self):
        v = _parse_verdict(SUCCESS_JSON)
        assert v["verdict"] == "success" and v["confidence"] == 0.9
        assert v["milestones"] == {"square clicked": True}

    def test_rejects_bad_verdict_word(self):
        assert _parse_verdict('{"verdict": "probably"}') is None

    def test_confidence_clamped(self):
        v = _parse_verdict('{"verdict": "fail", "confidence": 5}')
        assert v["confidence"] == 1.0


class TestJudgeRun:
    def test_double_run_agreement(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=4)
        judge = MockJudge([SUCCESS_JSON, SUCCESS_JSON])
        v = judge_run(run_dir, _spec(), judge)
        assert v.verdict == "success"
        assert v.agreement == "agree"
        assert judge.image_counts == [4, 4]  # double pass, same keyframe count

    def test_disagreement_takes_conservative(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=4)
        judge = MockJudge([SUCCESS_JSON, FAIL_JSON])
        v = judge_run(run_dir, _spec(), judge)
        assert v.verdict == "fail"  # strict-by-default on disagreement
        assert v.agreement == "disagree"

    def test_escalation_on_disagreement(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=4)
        judge = MockJudge([SUCCESS_JSON, FAIL_JSON])
        escalate = MockJudge([FAIL_JSON])
        v = judge_run(run_dir, _spec(), judge, escalate_agent=escalate)
        assert v.verdict == "fail"
        assert v.agreement == "escalated"

    def test_unparsable_judge_fails_closed(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=4)
        judge = MockJudge(["garbage", "still garbage"])
        v = judge_run(run_dir, _spec(), judge)
        assert v.verdict == "fail" and v.error  # fail closed, error recorded

    def test_verifiers_recorded(self, tmp_path):
        run_dir = _recorded_run(tmp_path, n_steps=4)
        judge = MockJudge([SUCCESS_JSON, SUCCESS_JSON])
        v = judge_run(run_dir, _spec(), judge, verifiers=["adapter:fakegame"])
        assert isinstance(v, Verdict)
        assert v.verifiers == ["adapter:fakegame"]  # the orchestrator appends "vlm"
