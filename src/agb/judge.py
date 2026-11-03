"""VLM judge (architecture 8): strict, frame-cited, never sees agent thoughts.

Double-run judging with shuffled frame order; on disagreement the more
conservative verdict wins and the disagreement is recorded. Adapter
deterministic verifiers (architecture 8.2) are wired in the orchestrator.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from agb.agent.parsing import extract_json_object
from agb.config import redact
from agb.models import TaskSpec

_MAX_FRAMES = 8
_JUDGE_FRAME_MAX_W = 512  # judge frames are downscaled; fits ~4096-context models


@dataclass
class Verdict:
    verdict: str  # success | partial | fail
    confidence: float
    cited_frames: list = field(default_factory=list)
    reasoning: str = ""
    milestones: dict = field(default_factory=dict)
    agreement: str = "single"  # single | agree | disagree | escalated
    verifiers: list = field(default_factory=list)
    error: str | None = None


def select_keyframes(run_dir: str | Path, max_frames: int = _MAX_FRAMES) -> list[Path]:
    """Baseline + claim/evidence tail + uniform sample of the run's frames."""
    run_dir = Path(run_dir)
    steps: list[dict] = []
    steps_file = run_dir / "steps.jsonl"
    if steps_file.exists():
        for line in steps_file.read_text(encoding="utf-8").splitlines():
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    frame_paths = [run_dir / s["frame"] for s in steps if s.get("frame")]
    existing = [p for p in frame_paths if p.exists()]
    if not existing:
        return []

    chosen: list[Path] = []
    baseline = run_dir / "baseline.jpg"
    if baseline.exists():
        chosen.append(baseline)
    tail = existing[-3:]  # the claim and evidence frames
    rest = [p for p in existing if p not in tail]
    budget = max_frames - len(chosen) - len(tail)
    if rest and budget > 0:
        step = max(1, len(rest) // budget)
        chosen.extend(rest[::step][:budget])
    chosen.extend(tail)
    return chosen[:max_frames]


def _verdict_prompt(task: TaskSpec, frame_count: int, frame_names: list[str]) -> str:
    milestones = ""
    if task.success.milestones:
        lines = "\n".join(f"- {m.name}: {m.check}" for m in task.success.milestones)
        milestones = f"\nMILESTONES (partial credit; score each true/false):\n{lines}"
    return (
        f"TASK GOAL: {task.goal}\n\n"
        f"SUCCESS EVIDENCE REQUIRED:\n{task.success.evidence}\n"
        + (f"\nEVIDENCE STEP: {task.success.evidence_step}\n" if task.success.evidence_step else "")
        + f"{milestones}\n"
        f"You are shown {frame_count} screenshots in this order: "
        f"{', '.join(frame_names)}. The first (when present) is the baseline "
        "before the run.\n\n"
        "Decide whether the task was accomplished, based ONLY on what is "
        "visible in these screenshots. Be strict: if the required evidence is "
        "not clearly visible, answer fail. You must cite frame names.\n\n"
        'Reply ONLY with JSON: {"verdict": "success|partial|fail", '
        '"confidence": 0.0-1.0, "cited_frames": ["..."], '
        '"reasoning": "...", "milestones": {"name": true|false}}'
    )


def _parse_verdict(raw: str) -> dict | None:
    obj = extract_json_object(raw)
    if not obj or "verdict" not in obj:
        return None
    v = str(obj["verdict"]).lower()
    if v not in ("success", "partial", "fail"):
        return None
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "verdict": v,
        "confidence": min(max(conf, 0.0), 1.0),
        "cited_frames": obj.get("cited_frames", []) or [],
        "reasoning": str(obj.get("reasoning", "")),
        "milestones": obj.get("milestones", {}) or {},
    }


def _one_pass(agent, prompt: str, frames: list[Path]) -> tuple[dict | None, str]:
    jpeg_frames = []
    try:
        jpeg_frames = [_downscale(p) for p in frames]
        d = agent.decide(
            "You are a strict verifier for a game-agent benchmark. Reply ONLY with JSON.",
            prompt,
            jpeg_frames,
        )
    except Exception as e:  # transport/endpoint errors fail closed, never crash the batch
        return None, f"judge call failed: {type(e).__name__}: {e}"
    parsed = _parse_verdict(d.raw)
    return parsed, ("" if parsed else f"unparsable judge reply: {redact(d.raw)[:120]}")


def _downscale(path: Path) -> bytes:
    """Judge frames are downscaled (context budget); counters stay legible."""
    img = Image.open(path)
    if img.width > _JUDGE_FRAME_MAX_W:
        ratio = _JUDGE_FRAME_MAX_W / img.width
        img = img.resize((_JUDGE_FRAME_MAX_W, max(1, int(img.height * ratio))))
    import io as _io

    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def judge_run(
    run_dir: str | Path,
    task: TaskSpec,
    judge_agent,
    *,
    escalate_agent=None,
    double: bool = True,
    verifiers: list | None = None,
) -> Verdict:
    """Judge a recorded run. Frames only — the judge never sees agent thoughts."""
    run_dir = Path(run_dir)
    frames = select_keyframes(run_dir)
    if not frames:
        return Verdict(verdict="fail", confidence=0.0, verifiers=verifiers or [],
                       error="no frames to judge")
    names = [p.name for p in frames]
    prompt = _verdict_prompt(task, len(frames), names)

    v1, err1 = _one_pass(judge_agent, prompt, frames)
    if v1 is None:  # one re-ask, strict fallback on failure
        v1, err2 = _one_pass(judge_agent, prompt + "\n\nReply ONLY with the JSON object.", frames)
        err1 = err2 or err1
    if v1 is None:
        return Verdict(verdict="fail", confidence=0.0, verifiers=verifiers or [],
                       error=err1 or "judge failed")

    agreement = "single"
    final = v1
    if double:
        shuffled = frames[:]
        random.Random(7).shuffle(shuffled)  # fixed seed: reproducible shuffle
        prompt2 = _verdict_prompt(task, len(shuffled), [p.name for p in shuffled])
        v2, _ = _one_pass(judge_agent, prompt2, shuffled)
        if v2 is None:
            agreement = "single"
        elif v2["verdict"] == v1["verdict"]:
            agreement = "agree"
            final = {**v1, "confidence": min(v1["confidence"], v2["confidence"])}
        else:
            agreement = "disagree"
            if escalate_agent is not None:
                # escalate: original frame order
                v3, _ = _one_pass(escalate_agent, prompt, frames)
                if v3 is not None:
                    final = v3
                    agreement = "escalated"
            if agreement == "disagree":
                # strict-by-default: fail beats partial beats success
                order = {"fail": 0, "partial": 1, "success": 2}
                final = v1 if order[v1["verdict"]] <= order[v2["verdict"]] else v2

    return Verdict(
        verdict=final["verdict"],
        confidence=final["confidence"],
        cited_frames=final["cited_frames"],
        reasoning=final["reasoning"],
        milestones=final["milestones"],
        agreement=agreement,
        verifiers=verifiers or [],
    )
