"""agb command line: capture-debugging helpers and the run command."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer

from agb.config import ensure_dpi_awareness

# adapters/ lives at the repo root (deliberately outside the installed package);
# make it importable for the console-script entry point.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

app = typer.Typer(help="AnyGame-Bench harness", no_args_is_help=True)


@app.command()
def windows() -> None:
    """List visible windows (title, size, position) to debug capture targets."""
    ensure_dpi_awareness()
    import pygetwindow as gw

    for w in gw.getAllWindows():
        if w.title and w.width > 0 and w.height > 0:
            print(f"{w.width:>5}x{w.height:<5} @ ({w.left:>5},{w.top:>5})  {w.title}")


def _open_capture(title: str, max_w: int = 1280, max_h: int = 720):
    from agb.capture import WindowCapture, WindowNotFoundError

    try:
        return WindowCapture(title, max_w=max_w, max_h=max_h)
    except WindowNotFoundError:
        return None


@app.command()
def run(
    task: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="Task spec YAML"
    ),
    model: str = typer.Option(
        ..., "--model", "-m", help="Model profile name from models.yaml"
    ),
    max_steps: int | None = typer.Option(None, min=1, help="Override the task's step cap"),
    window_title: str | None = typer.Option(
        None, help="Override the window title to capture"
    ),
    launch: bool = typer.Option(
        False, "--launch", help="Launch the game via its adapter if the window is missing"
    ),
    view_max: str = typer.Option(
        "640x480",
        "--view-max",
        help="Max agent view WxH; smaller views = fewer vision tokens = faster local models",
    ),
) -> None:
    """Run one task with one agent; prints a results row and writes runs/<id>/result.json.

    The agent's done claim is never evidence (architecture 8): success comes
    from the game adapter's deterministic check, judged against the window
    state after the run.
    """
    ensure_dpi_awareness()
    from adapters import get_adapter

    from agb.config import build_agent
    from agb.inputs import WindowInput
    from agb.killswitch import KillSwitch
    from agb.loop import execute
    from agb.models import load_task_spec

    spec = load_task_spec(task)
    adapter = get_adapter(spec.game)
    try:
        vw, vh = (int(v) for v in view_max.lower().split("x"))
    except ValueError:
        typer.secho(f"--view-max must be WxH, got {view_max!r}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    kill = KillSwitch()
    if not kill.armed:
        typer.secho("Kill switch failed to arm; refusing to run.", fg=typer.colors.RED)
        raise typer.Exit(1)

    title = window_title or adapter.WINDOW_TITLE
    launched = None
    if launch:
        adapter.close_all()  # hermetic runs: no stale game state
    capture = _open_capture(title, vw, vh)
    if capture is None and launch:
        launched = adapter.launch()
        deadline = time.time() + 20
        while capture is None and time.time() < deadline:
            time.sleep(0.3)
            capture = _open_capture(title, vw, vh)
    if capture is None:
        typer.secho(
            f"No window matching {title!r}. Open the game first or pass --launch.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    try:
        agent = build_agent(model)
        result = execute(
            spec, agent, capture, WindowInput(capture), kill, max_steps=max_steps
        )
        # read the game state while the window is still alive (the game adapter
        # reads progress from the window title)
        state = adapter.read_state(capture.win.title)
        success = adapter.check_success(spec, state)
    finally:
        if launched is not None:
            launched.terminate()

    run_id = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    run_dir = Path("runs") / f"{run_id}_{spec.id}_{model}"
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run_dir.name,
        "task_id": spec.id,
        "model": model,
        "agent_mode": "A",
        "assist_level": spec.loop.assist_level,
        "time_mode": spec.loop.time_mode,
        "outcome": result.outcome,
        "success": success,
        "adapter_state": state,
        "steps": result.steps,
        "model_calls": result.model_calls,
        "invalid_outputs": result.invalid_outputs,
        "invalid_rate": round(result.invalid_rate, 3),
        "invalid_actions": result.invalid_actions,
        "stuck_events": result.stuck_events,
        "wall_seconds": round(result.wall_seconds, 1),
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": round(result.cost_usd, 6),
        "avg_latency_ms": round(result.avg_latency_ms),
        "errors": result.errors,
        "raw_samples": result.raw_samples,
        "frame_scale": result.frame_scale,
    }
    (run_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    typer.echo(
        f"{spec.id:<28} {model:<12} {result.outcome:<12} success={success!s:<5} "
        f"steps={result.steps:<3} invalid={result.invalid_rate:.0%} "
        f"stuck={result.stuck_events} avg_ms={record['avg_latency_ms']:.0f} "
        f"tok={result.tokens_in}/{result.tokens_out} cost=${result.cost_usd:.4f}"
    )
    typer.echo(f"artifacts: {run_dir / 'result.json'}")


if __name__ == "__main__":
    app()
