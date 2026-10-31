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
from agb.recorder import Recorder
from agb.replay import generate as generate_replay


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
    try:
        result = execute(
            spec, agent, capture, WindowInput(capture), kill,
            recorder=recorder, max_steps=max_steps,
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
