"""Run orchestrator: owns the lifecycle and the run-folder contract (Sprint 2).

Folder layout: runs/<utc>_<task_id>_<model>_n<N>/
  steps.jsonl  frames/  run.mp4  replay.html  result.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agb.inputs import WindowInput
from agb.killswitch import KillSwitch
from agb.loop import LoopResult, execute
from agb.models import TaskSpec
from agb.planner import make_plan, replan
from agb.recorder import Recorder
from agb.replay import generate as generate_replay
from agb.research import research

_TASKS_ROOT = Path(__file__).resolve().parents[2] / "tasks"


def _load_provided_brief(spec: TaskSpec) -> str:
    """Provided-mode brief convention: tasks/<game>/<task_id>.brief.md."""
    path = _TASKS_ROOT / spec.game / f"{spec.id}.brief.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def next_run_number(runs_root: Path, task_id: str, model: str) -> int:
    """Count existing runs for this (task, model) pair; the new one is n+1."""
    if not runs_root.exists():
        return 1
    suffix = f"_{task_id}_{model}_n"
    return sum(1 for p in runs_root.iterdir() if p.is_dir() and suffix in p.name) + 1


def make_run_dir(runs_root: Path, spec: TaskSpec, model: str) -> Path:
    run_id = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    n = next_run_number(runs_root, spec.id, model)
    run_dir = runs_root / f"{run_id}_{spec.id}_{model}_n{n}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run(
    spec: TaskSpec,
    agent,
    capture,
    kill: KillSwitch,
    runs_root: Path,
    *,
    launched=None,
    view_max: tuple[int, int] = (640, 480),
    max_steps: int | None = None,
    research_mode: str | None = None,
) -> dict[str, Any]:
    """Execute one task with one agent and persist the full run folder.

    The agent is injected (CLI resolves model profiles; tests inject mocks).
    Returns the result record (also written as result.json).
    """
    from adapters import get_adapter

    adapter = get_adapter(spec.game)
    run_dir = make_run_dir(runs_root, spec, agent.name)
    recorder = Recorder(run_dir)
    recorder.start_video(capture.rect())
    result: LoopResult | None = None
    error: str | None = None
    state: dict = {}
    success = False
    research_result = None
    plan = None
    research_usage: dict = {"in_tokens": 0, "out_tokens": 0}
    plan_usage: dict = {"in_tokens": 0, "out_tokens": 0}
    research_error = None
    try:
        # RESEARCH phase (architecture 6 step 1)
        mode = research_mode or spec.research.mode
        provided = _load_provided_brief(spec) if mode == "provided" else ""
        research_result = research(
            spec.goal, spec.game, agent, mode, run_dir,
            max_minutes=spec.research.max_minutes, provided_text=provided,
        )
        research_usage = research_result.usage
        research_error = research_result.error

        # PLAN phase (architecture 6 step 2)
        plan, plan_usage, plan_seconds = make_plan(spec.goal, research_result.brief, agent, run_dir)

        def _replan_fn(progress: list[str]):
            new_plan, _, _ = replan(
                spec.goal, research_result.brief, plan, progress, agent, run_dir
            )
            return new_plan

        result = execute(
            spec, agent, capture, WindowInput(capture), kill,
            recorder=recorder, plan=plan, replan_fn=_replan_fn,
            max_steps=max_steps,
        )
        # read the game state while the window is still alive (the fake-game
        # adapter reads progress from the window title)
        state = adapter.read_state(capture.win.title)
        success = adapter.check_success(spec, state)
    except Exception as e:  # a crashed run still writes its partial result
        error = f"{type(e).__name__}: {e}"
    finally:
        recorder.close()
        if launched is not None:
            launched.terminate()

    record: dict[str, Any] = {
        "run_id": run_dir.name,
        "task_id": spec.id,
        "model": agent.name,
        "agent_mode": "A",
        "assist_level": spec.loop.assist_level,
        "time_mode": spec.loop.time_mode,
        "research_mode": research_result.mode if research_result else spec.research.mode,
        "research_seconds": round(research_result.seconds, 1) if research_result else 0.0,
        "research_tokens_in": research_usage.get("in_tokens", 0),
        "research_tokens_out": research_usage.get("out_tokens", 0),
        "research_error": research_error,
        "plan_seconds": round(plan_seconds, 1) if plan_seconds is not None else None,
        "plan_tokens_in": plan_usage.get("in_tokens", 0),
        "plan_tokens_out": plan_usage.get("out_tokens", 0),
        "replans": result.replans if result else 0,
        "view_max": list(view_max),
        "outcome": result.outcome if result else "error",
        "success": success,
        "adapter_state": state,
        "steps": result.steps if result else 0,
        "model_calls": result.model_calls if result else 0,
        "invalid_outputs": result.invalid_outputs if result else 0,
        "invalid_rate": round(result.invalid_rate, 3) if result else 0.0,
        "invalid_actions": result.invalid_actions if result else 0,
        "stuck_events": result.stuck_events if result else 0,
        "wall_seconds": round(result.wall_seconds, 1) if result else 0.0,
        "tokens_in": result.tokens_in if result else 0,
        "tokens_out": result.tokens_out if result else 0,
        "cost_usd": round(result.cost_usd, 6) if result else 0.0,
        "avg_latency_ms": round(result.avg_latency_ms) if result else 0,
        "frame_scale": list(result.frame_scale) if result and result.frame_scale else None,
        "errors": result.errors if result else ([error] if error else []),
        "raw_samples": result.raw_samples if result else [],
    }
    (run_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    replay_path = generate_replay(run_dir)
    record["replay"] = str(replay_path)
    return record
