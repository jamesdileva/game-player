"""agb command line: run, replay, and capture-debugging helpers."""

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


def result_row(record: dict) -> None:
    typer.echo(
        f"{record['task_id']:<28} {record['model']:<12} {record['outcome']:<12} "
        f"success={record['success']!s:<5} steps={record['steps']:<3} "
        f"invalid={record['invalid_rate']:.0%} stuck={record['stuck_events']} "
        f"avg_ms={record['avg_latency_ms']:.0f} "
        f"tok={record['tokens_in']}/{record['tokens_out']} cost=${record['cost_usd']:.4f}"
    )
    typer.echo(f"artifacts: runs/{record['run_id']}")

FAILURE_CATEGORIES = (
    "research_wrong", "plan_infeasible", "perception", "grounding",
    "navigation_lost", "stuck_loop", "ui_modal", "timing", "premature_done",
    "budget", "precision", "none",
)


def _prepare_capture(adapter, window_title: str | None, launch: bool, vw: int, vh: int):
    """Find (or launch) the game window; returns (capture, launched_process)."""
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
    return capture, launched


def _apply_task_overrides(
    spec, assist: str | None, research: str | None, time_mode: str | None = None,
    mode: str | None = None,
):
    if mode is not None:
        if mode not in ("agent", "reflex"):
            typer.secho(
                f"--mode must be agent or reflex, got {mode!r}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        spec.loop.mode = mode
    if time_mode is not None:
        if time_mode not in ("realtime", "paused"):
            typer.secho(
                f"--time-mode must be realtime or paused, got {time_mode!r}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        spec.loop.time_mode = time_mode
    if assist is not None:
        if assist not in ("L0", "L1", "L2"):
            typer.secho(f"--assist must be L0, L1 or L2, got {assist!r}", fg=typer.colors.RED)
            raise typer.Exit(1)
        spec.loop.assist_level = assist
    if research is not None:
        if research not in ("none", "web", "provided"):
            typer.secho(
                f"--research must be none, web or provided, got {research!r}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        spec.research.mode = research


def summarize_matrix(records: list[dict]) -> str:
    """Per-model aggregate lines for a matrix batch."""
    by_model: dict[str, list[dict]] = {}
    for r in records:
        by_model.setdefault(r["model"], []).append(r)
    lines = ["model           runs successes mean_steps mean_invalid mean_ms"]
    for model, rs in by_model.items():
        n = len(rs)
        succ = sum(1 for r in rs if r["success"])
        steps = sum(r["steps"] for r in rs) / n
        inv = sum(r["invalid_rate"] for r in rs) / n
        ms = sum(r["avg_latency_ms"] for r in rs) / n
        lines.append(f"{model:<15} {n:>4} {succ:>9} {steps:>10.1f} {inv:>11.0%} {ms:>7.0f}")
    return chr(10).join(lines)


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
        "512x384",
        "--view-max",
        help="Max agent view WxH (512x384 adopted: best invalid-rate in the A/B)",
    ),
    assist: str | None = typer.Option(
        None, "--assist", help="Override the task's assist level (L0 | L1 | L2)"
    ),
    research: str | None = typer.Option(
        None, "--research", help="Override the task's research mode (none | web | provided)"
    ),
    judge: str | None = typer.Option(
        None, "--judge", help="Model profile to judge the run (omit: adapter-only verdict)"
    ),
    time_mode: str | None = typer.Option(
        None, "--time-mode", help="Override the task's time mode (realtime | paused)"
    ),
    mode: str | None = typer.Option(
        None, "--mode", help="Override the loop mode (agent | reflex)"
    ),
) -> None:
    """Run one task with one agent; prints a results row and persists the full run folder.

    The agent's done claim is never evidence (architecture 8): success comes
    from the game adapter's deterministic check, judged against the window
    state after the run.
    """
    ensure_dpi_awareness()
    from adapters import get_adapter

    from agb.config import build_agent
    from agb.killswitch import KillSwitch
    from agb.models import load_task_spec

    spec = load_task_spec(task)
    _apply_task_overrides(spec, assist, research, time_mode, mode)
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

    capture, launched = _prepare_capture(adapter, window_title, launch, vw, vh)
    if capture is None:
        typer.secho(
            f"No window matching {window_title or adapter.WINDOW_TITLE!r}. "
            "Open the game first or pass --launch.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    from agb.orchestrator import run as run_orchestrated

    record = run_orchestrated(
        spec, build_agent(model), capture, kill, Path("runs"),
        launched=launched, view_max=(vw, vh), max_steps=max_steps,
        research_mode=research,
        judge_agent=build_agent(judge) if judge else None,
    )
    result_row(record)


@app.command()
def matrix(
    task: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    models: str = typer.Option(..., "--models", help="Comma-separated model profile names"),
    runs_per_model: int = typer.Option(3, "--runs", min=1, help="Runs per model"),
    max_steps: int | None = typer.Option(None, min=1),
    window_title: str | None = typer.Option(None),
    launch: bool = typer.Option(False, "--launch"),
    view_max: str = typer.Option("640x480", "--view-max"),
    assist: str | None = typer.Option(None, "--assist"),
    research: str | None = typer.Option(None, "--research"),
    judge: str | None = typer.Option(None, "--judge"),
    time_mode: str | None = typer.Option(None, "--time-mode"),
) -> None:
    """Run the same task across several models sequentially; prints a batch table.

    Runs are NOT ranked at n < 5 (architecture 9.2). For --launch games the
    window is reused across runs; game state persists between them.
    """
    ensure_dpi_awareness()
    from adapters import get_adapter

    from agb.config import build_agent
    from agb.killswitch import KillSwitch
    from agb.models import load_task_spec
    from agb.orchestrator import run as run_orchestrated

    _apply_task_overrides(load_task_spec(task), assist, research, time_mode)  # validates early
    adapter = get_adapter(load_task_spec(task).game)
    try:
        vw, vh = (int(v) for v in view_max.lower().split("x"))
    except ValueError:
        typer.secho(f"--view-max must be WxH, got {view_max!r}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    kill = KillSwitch()
    if not kill.armed:
        typer.secho("Kill switch failed to arm; refusing to run.", fg=typer.colors.RED)
        raise typer.Exit(1)

    capture, launched = _prepare_capture(adapter, window_title, launch, vw, vh)
    if capture is None:
        typer.secho(
            f"No window matching {window_title or adapter.WINDOW_TITLE!r}. "
            "Open the game first or pass --launch.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    judge_agent = build_agent(judge) if judge else None
    model_names = [m.strip() for m in models.split(",") if m.strip()]
    records = []
    for model in model_names:
        for n in range(runs_per_model):
            typer.echo(f"--- matrix: {model} run {n + 1}/{runs_per_model}")
            spec = load_task_spec(task)  # fresh spec per run
            _apply_task_overrides(spec, assist, research, time_mode)
            record = run_orchestrated(
                spec, build_agent(model), capture, kill, Path("runs"),
                launched=launched, view_max=(vw, vh), max_steps=max_steps,
                research_mode=research, judge_agent=judge_agent,
            )
            result_row(record)
            records.append(record)
    typer.echo(summarize_matrix(records))


@app.command()
def label(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    verdict: str = typer.Argument(..., help="Human verdict: success | partial | fail"),
    category: str = typer.Option(
        "none", "--category", help=f"Failure category: {', '.join(FAILURE_CATEGORIES)}"
    ),
) -> None:
    """Append a human label to the run's labels.jsonl (ground truth for calibration)."""
    if verdict not in ("success", "partial", "fail"):
        typer.secho("verdict must be success, partial or fail", fg=typer.colors.RED)
        raise typer.Exit(1)
    if category not in FAILURE_CATEGORIES:
        typer.secho(f"unknown category {category!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    entry = {
        "run_id": run_dir.name,
        "human": verdict,
        "category": category,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }
    with open(run_dir / "labels.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    typer.echo(f"labeled: {run_dir.name} = {verdict}")


@app.command()
def calibrate(
    judge: str = typer.Option(..., "--judge", help="Model profile to use as the VLM judge"),
    runs: Path = typer.Option(Path("runs"), "--runs", help="Root folder of run folders"),
) -> None:
    """Judge recorded runs and measure agreement with ground-truth labels.

    Ground truth: the fake-game adapter's deterministic state where available,
    otherwise the run's human label (labels.jsonl).
    """
    from agb.config import build_agent
    from agb.judge import judge_run
    from agb.models import load_task_spec

    judge_agent = build_agent(judge)
    spec_cache: dict[str, object] = {}
    rows = []

    for run_dir in sorted(p for p in runs.iterdir() if p.is_dir()):
        result_file = run_dir / "result.json"
        if not result_file.exists():
            continue
        result = json.loads(result_file.read_text(encoding="utf-8"))
        task_file = None
        for yaml_path in Path("tasks").rglob("*.yaml"):
            if result["task_id"] in yaml_path.read_text(encoding="utf-8"):
                task_file = yaml_path
                break
        if task_file is None:
            continue
        spec = spec_cache.get(result["task_id"])
        if spec is None:
            spec = load_task_spec(task_file)
            spec_cache[result["task_id"]] = spec

        # ground truth: adapter success recorded at run time, else human label
        truth = None
        source = None
        if result.get("adapter_state") and result["adapter_state"].get("stage") is not None:
            truth = "success" if result.get("success") else "fail"
            source = "adapter"
        else:
            labels = run_dir / "labels.jsonl"
            if labels.exists():
                last = [
                    json.loads(x)
                    for x in labels.read_text(encoding="utf-8").splitlines()
                    if x.strip()
                ]
                if last:
                    truth = last[-1]["human"]
                    source = "human"
        if truth is None:
            continue

        v = judge_run(run_dir, spec, judge_agent, double=True)
        rows.append({
            "run_id": result["run_id"],
            "truth": truth,
            "judge": v.verdict,
            "confidence": v.confidence,
            "agreement": v.agreement,
            "match": v.verdict == truth,
            "source": source,
        })

    n = len(rows)
    matches = sum(1 for r in rows if r["match"])
    fp = sum(1 for r in rows if r["truth"] == "fail" and r["judge"] != "fail")
    fn = sum(1 for r in rows if r["truth"] == "success" and r["judge"] != "success")
    report = {
        "judge": judge,
        "n": n,
        "agreement": round(matches / n, 3) if n else None,
        "false_positive_rate": round(fp / n, 3) if n else None,
        "false_negative_rate": round(fn / n, 3) if n else None,
        "per_run": rows,
    }
    out = runs / "judge_calibration.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    typer.echo(
        f"judge agreement: {report['agreement']} over {n} runs "
        f"(FP={report['false_positive_rate']} FN={report['false_negative_rate']})"
    )
    typer.echo(f"written: {out}")


@app.command()
def serve(
    task: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="Task spec YAML"
    ),
    max_steps: int | None = typer.Option(None, min=1, help="Override the task's step cap"),
    window_title: str | None = typer.Option(
        None, help="Override the window title to capture"
    ),
    view_max: str = typer.Option(
        "384x288", "--view-max", help="Max agent view WxH served to MCP clients"
    ),
    judge: str | None = typer.Option(
        None, "--judge", help="Judge model profile (runs after the episode ends)"
    ),
) -> None:
    """Mode B: serve a game as MCP tools over stdio (architecture 5.5).

    An MCP client (another agent) drives the game through
    screenshot/click/key/note/done; the harness records every call, enforces
    the caps, and judges the recording when the episode ends.
    """
    ensure_dpi_awareness()
    from adapters import get_adapter

    from agb.killswitch import KillSwitch
    from agb.mcp_server import build_server, load_session
    from agb.models import load_task_spec
    from agb.recorder import Recorder

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

    # NO eager capture here: MCP clients spawn the server before the game is
    # up. The session connects lazily on the first tool call, and the video
    # recording starts once the game is wired. stdout must stay clean (stdio).
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    run_dir = Path("runs") / f"{stamp}_{spec.id}_modeB"
    run_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(run_dir)

    session = load_session(task, window_title, max_steps, view_max, recorder=recorder)
    server = build_server(session)
    typer.echo(
        f"Mode B serving: {spec.id} (steps cap {session.max_steps}, "
        f"game connects lazily on first tool call). "
        "Judging runs when the client disconnects.",
        err=True,
    )

    try:
        server.run()  # stdio transport; blocks until the client disconnects
    finally:
        recorder.close()

    outcome = "done" if session.done_claim else "incomplete"
    state = {}
    if session.wired:  # the game was connected: read its final state
        try:
            state = adapter.read_state(session.capture.win.title)
        except Exception:
            pass
    success = adapter.check_success(spec, state)
    record = {
        "run_id": run_dir.name,
        "task_id": spec.id,
        "model": "mcp-client",
        "agent_mode": "B",
        "mode": "paused" if spec.loop.time_mode == "paused" else "realtime",
        "outcome": outcome,
        "success": success,
        "adapter_state": state,
        "steps": session.tool_calls,
        "invalid_rate": 0.0,
        "done_claim": session.done_claim,
        "verdict": None,
        "verifiers": ["adapter"] if success is not None else [],
    }
    (run_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if judge:
        typer.echo(
            f"note: --judge {judge!r} scores this recording via "
            "`agb calibrate --judge` after the episode", err=True,
        )
    typer.echo(f"Mode B episode recorded: {run_dir}", err=True)
    result_row(record)


@app.command()
def report(
    runs: Path = typer.Option(Path("runs"), "--runs", help="Root folder of run folders"),
) -> None:
    """Aggregate all recorded runs into report.db + report.html (no rankings at n<5)."""
    from agb.report import build_report

    summary = build_report(runs)
    typer.echo(f"runs: {summary['total_runs']}")
    for g in summary["groups"]:
        rank = "" if g["ranked"] else "  (not ranked, n<5)"
        typer.echo(
            f"{g['task_id']:<28} {g['model']:<12} n={g['n']:<3} "
            f"successes={g['successes']:<3} rate={g['success_rate']:.0%} "
            f"median_steps={g['median_steps']:.0f} "
            f"judge_agree={g['judge_agreement'] if g['judge_agreement'] is not None else '-'}"
            f"{rank}"
        )
    judge = summary["judge"]
    typer.echo(
        f"judge agreement: {judge.agreement} over {judge.n} (FP={judge.false_positive_rate} "
        f"FN={judge.false_negative_rate}); self-judged runs: {judge.self_judged_runs}"
    )
    typer.echo(f"artifacts: {summary['db']}, {summary['html']}")


@app.command()
def replay(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Generate (if needed) and open a run's replay page in the browser."""
    from agb.replay import generate

    page = generate(run_dir)
    import webbrowser

    webbrowser.open(page.resolve().as_uri())
    typer.echo(f"replay: {page}")


if __name__ == "__main__":
    app()
