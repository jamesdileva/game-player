"""Planner (architecture 5.8): goal + brief -> ordered subgoals with checks.

The plan is saved as plan.md and re-read by the agent every step. Subgoal
advancement becomes meaningful in Sprint 4 (milestone checks); until then the
whole plan is injected and replans regenerate it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from agb.agent.parsing import extract_json_object
from agb.config import redact

_MAX_SUBGOALS = 5


@dataclass
class Plan:
    subgoals: list[dict]  # {"text": str, "check": str}

    def render(self) -> str:
        lines = [
            f"{i + 1}. {s.get('text', '?')}  "
            f"(check: {s.get('check', 'observable change')})"
            for i, s in enumerate(self.subgoals)
        ]
        return "\n".join(lines)


def _plan_from_reply(raw: str) -> Plan | None:
    obj = extract_json_object(raw)
    if not obj:
        return None
    subs = obj.get("subgoals")
    if not isinstance(subs, list) or not subs:
        return None
    cleaned = []
    for s in subs[:_MAX_SUBGOALS]:
        if isinstance(s, str):
            cleaned.append({"text": s, "check": "observable change"})
        elif isinstance(s, dict) and s.get("text"):
            check = str(s.get("check", "observable change"))
            cleaned.append({"text": str(s["text"]), "check": check})
    return Plan(subgoals=cleaned) if cleaned else None


def _call(agent, prompt: str) -> tuple[str, dict]:
    d = agent.decide(
        "You are a game task planner. Reply ONLY with JSON.",
        prompt,
        [],
    )
    return d.raw, {
        "in_tokens": int(d.usage.get("in_tokens", 0) or 0),
        "out_tokens": int(d.usage.get("out_tokens", 0) or 0),
    }


def make_plan(goal: str, brief: str, agent, run_dir: str | Path) -> tuple[Plan | None, dict, float]:
    """Goal + brief -> Plan (or None), usage, seconds. Writes plan.md."""
    t0 = time.perf_counter()
    prompt = (
        f"GOAL: {goal}\n\nRESEARCH BRIEF:\n{brief[:4000]}\n\n"
        'Break this into 2-5 ordered subgoals, each with an observable screen check. '
        'Reply ONLY with JSON: {"subgoals": [{"text": "...", "check": "..."}]}'
    )
    raw, usage = _call(agent, prompt)
    plan = _plan_from_reply(raw)
    if plan is None:  # one re-ask with feedback
        raw, u2 = _call(
            agent,
            prompt + "\n\nYour previous reply was not usable. Reply ONLY with the JSON object.",
        )
        usage["in_tokens"] += u2["in_tokens"]
        usage["out_tokens"] += u2["out_tokens"]
        plan = _plan_from_reply(raw)

    seconds = time.perf_counter() - t0
    text = (
        f"# Plan\n\nGOAL: {goal}\n\n"
        + (plan.render() if plan else "(planning failed; the agent will improvise)")
    )
    (Path(run_dir) / "plan.md").write_text(redact(text) + "\n", encoding="utf-8")
    return plan, usage, seconds


def replan(
    goal: str, brief: str, old_plan: Plan | None, progress: list[str],
    agent, run_dir: str | Path,
) -> tuple[Plan | None, dict, float]:
    """Regenerate the plan given what has been tried (stuck or agent request)."""
    t0 = time.perf_counter()
    old = old_plan.render() if old_plan else "(none)"
    recent = "\n".join(progress[-6:]) or "(nothing notable)"
    prompt = (
        f"GOAL: {goal}\n\nBRIEF:\n{brief[:3000]}\n\nOLD PLAN:\n{old}\n\n"
        f"RECENT PROGRESS:\n{recent}\n\n"
        "The approach is stuck. Produce a revised plan with a different "
        "approach. Reply ONLY with JSON: "
        '{"subgoals": [{"text": "...", "check": "..."}]}'
    )
    raw, usage = _call(agent, prompt)
    plan = _plan_from_reply(raw)
    seconds = time.perf_counter() - t0
    if plan:
        (Path(run_dir) / "plan.md").write_text(
            redact(f"# Plan (revised)\n\n{plan.render()}") + "\n", encoding="utf-8"
        )
    return plan, usage, seconds
