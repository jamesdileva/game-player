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
    assist: str | None = typer.Option(
        None, "--assist", help="Override the task's assist level (L0 | L1 | L2)"
    ),
    research: str | None = typer.Option(
        None, "--research", help="Override the task's research mode (none | web | provided)"
    ),
    judge: str | None = typer.Option(
        None, "--judge", help="Model profile to judge the run (omit: adapter-only verdict)"
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

    from agb.orchestrator import run as run_orchestrated

    record = run_orchestrated(
        spec, build_agent(model), capture, kill, Path("runs"),
        launched=launched, view_max=(vw, vh), max_steps=max_steps,
        research_mode=research,
        judge_agent=build_agent(judge) if judge else None,
    )
    result_row(record)


@app.command()
def label(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    verdict: str = typer.Argument(..., help="Human verdict: success | partial | fail"),
) -> None:
    """Append a human label to the run's labels.jsonl (ground truth for calibration)."""
    if verdict not in ("success", "partial", "fail"):
        typer.secho("verdict must be success, partial or fail", fg=typer.colors.RED)
        raise typer.Exit(1)
    entry = {
        "run_id": run_dir.name,
        "human": verdict,
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
def replay(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Generate (if needed) and open a run's replay page in the browser."""
    from agb.replay import generate

    page = generate(run_dir)
    import webbrowser

    webbrowser.open(page.resolve().as_uri())
    typer.echo(f"replay: {page}")


if __name__ == "__main__":
    app()
