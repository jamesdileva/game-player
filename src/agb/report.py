"""Report generation (Sprint 7): aggregate run results into tables + a results page.

Reads every runs/<dir>/result.json plus human labels and the judge
calibration report. Produces:
  - runs/report.db     (SQLite: runs + labels tables)
  - runs/report.html   (static results page; links each run's replay)
  - an aggregate dict  (per task/model: n, success rate, medians, IQR,
    failure-category histogram, judge agreement - never ranked at n < 5)
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

_MIN_RANK_N = 5  # architecture 9.2: never rank below n = 5


@dataclass
class JudgeSummary:
    n: int = 0
    agreement: float | None = None
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    self_judged_runs: int = 0
    source: str = ""


def _load_labels(run_dir: Path) -> dict:
    """The run's most recent human label (verdict + failure category)."""
    labels = run_dir / "labels.jsonl"
    if not labels.exists():
        return {}
    last: dict = {}
    for line in labels.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def load_runs(runs_root: Path) -> list[dict]:
    """Load every recorded run with its label and verdict attached."""
    rows: list[dict] = []
    for run_dir in sorted(p for p in Path(runs_root).iterdir() if p.is_dir()):
        result_file = run_dir / "result.json"
        if not result_file.exists():
            continue
        try:
            d = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        label = _load_labels(run_dir)
        verdict = d.get("verdict") or {}
        # success signal precedence: human label > deterministic adapter check
        # (d["success"]) > VLM judge verdict. Manual games (OSRS/ToS/Dolphin)
        # have no adapter check, so their successes live in labels or verdicts.
        if label.get("human") is not None:
            effective_success = label["human"] == "success"
        elif d.get("success"):
            effective_success = True
        elif verdict.get("verdict"):
            effective_success = verdict.get("verdict") == "success"
        else:
            effective_success = False
        rows.append({
            "effective_success": effective_success,
            "run_id": d.get("run_id", run_dir.name),
            "task_id": d.get("task_id", ""),
            "model": d.get("model", ""),
            "mode": d.get("time_mode", ""),
            "outcome": d.get("outcome", ""),
            "success": d.get("success", False),
            "steps": d.get("steps", 0),
            "invalid_rate": d.get("invalid_rate", 0.0),
            "invalid_actions": d.get("invalid_actions", 0),
            "stuck_events": d.get("stuck_events", 0),
            "wall_seconds": d.get("wall_seconds", 0.0),
            "avg_latency_ms": d.get("avg_latency_ms", 0),
            "tokens_in": d.get("tokens_in", 0),
            "tokens_out": d.get("tokens_out", 0),
            "cost_usd": d.get("cost_usd", 0.0),
            "judge_verdict": verdict.get("verdict"),
            "judge_confidence": verdict.get("confidence"),
            "self_judged": verdict.get("self_judged", False),
            "human_verdict": label.get("human"),
            "category": label.get("category"),
            "replay": str(run_dir / "replay.html"),
        })
    return rows


def _iqr(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    vs = sorted(values)
    q1 = vs[len(vs) // 4]
    q3 = vs[(len(vs) * 3) // 4]
    return (q1, q3)


def aggregate(rows: list[dict]) -> dict:
    """Per (task_id, model) aggregates with the no-rank-below-n=5 rule."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["task_id"], r["model"])].append(r)

    aggregates = []
    for (task_id, model), rs in sorted(groups.items()):
        n = len(rs)
        successes = sum(1 for r in rs if r["effective_success"])
        steps = [float(r["steps"]) for r in rs]
        walls = [float(r["wall_seconds"]) for r in rs]
        inv = [float(r["invalid_rate"]) for r in rs]
        q1s, q3s = _iqr(steps)
        categories = Counter(r["category"] for r in rs if r.get("category"))
        judgments = [(r.get("human_verdict"), r.get("judge_verdict")) for r in rs]
        judged = [(h, j) for h, j in judgments if h and j]
        agree = sum(1 for h, j in judged if h == j)
        aggregates.append({
            "task_id": task_id,
            "model": model,
            "n": n,
            "successes": successes,
            "success_rate": round(successes / n, 3),
            "median_steps": statistics.median(steps),
            "iqr_steps": (q1s, q3s),
            "median_wall_s": round(statistics.median(walls), 1),
            "median_invalid": round(statistics.median(inv), 3),
            "failure_categories": dict(categories),
            "judge_labeled_pairs": len(judged),
            "judge_agreement": round(agree / len(judged), 3) if judged else None,
            "ranked": n >= _MIN_RANK_N,
        })
    return {"groups": aggregates, "total_runs": len(rows)}


def judge_summary(runs_root: Path, rows: list[dict]) -> JudgeSummary:
    """Judge accuracy: the calibrate report when present, else computed from
    per-run judge-vs-human label pairs."""
    summary = JudgeSummary()
    calib = Path(runs_root) / "judge_calibration.json"
    if calib.exists():
        try:
            d = json.loads(calib.read_text(encoding="utf-8"))
            summary.n = d.get("n", 0)
            summary.agreement = d.get("agreement")
            summary.false_positive_rate = d.get("false_positive_rate")
            summary.false_negative_rate = d.get("false_negative_rate")
            summary.source = "judge_calibration.json"
        except json.JSONDecodeError:
            pass

    if summary.agreement is None:
        judged = [(r.get("human_verdict"), r.get("judge_verdict")) for r in rows]
        judged = [(h, j) for h, j in judged if h and j]
        if judged:
            summary.n = len(judged)
            summary.agreement = round(
                sum(1 for h, j in judged if h == j) / len(judged), 3
            )
            summary.false_positive_rate = round(
                sum(1 for h, j in judged if h == "fail" and j != "fail") / len(judged), 3
            )
            summary.false_negative_rate = round(
                sum(1 for h, j in judged if h == "success" and j != "success") / len(judged), 3
            )
            summary.source = "per-run labels"

    summary.self_judged_runs = sum(1 for r in rows if r.get("self_judged"))
    return summary


def write_sqlite(runs_root: Path, rows: list[dict], aggregates: dict) -> Path:
    db = Path(runs_root) / "report.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "run_id TEXT PRIMARY KEY, task_id TEXT, model TEXT, mode TEXT, outcome TEXT,"
        "success INTEGER, steps INTEGER, invalid_rate REAL, wall_seconds REAL,"
        "avg_latency_ms INTEGER, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL,"
        "judge_verdict TEXT, judge_confidence REAL, self_judged INTEGER,"
        "human_verdict TEXT, category TEXT, replay TEXT)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS aggregates ("
                "task_id TEXT, model TEXT, n INTEGER, successes INTEGER,"
                "success_rate REAL, median_steps REAL, ranked INTEGER,"
                "PRIMARY KEY (task_id, model))")
    con.execute("DELETE FROM runs")
    con.execute("DELETE FROM aggregates")
    for r in rows:
        con.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["run_id"], r["task_id"], r["model"], r["mode"], r["outcome"],
             int(r["effective_success"]), r["steps"], r["invalid_rate"], r["wall_seconds"],
             r["avg_latency_ms"], r["tokens_in"], r["tokens_out"], r["cost_usd"],
             r["judge_verdict"], r["judge_confidence"], int(r["self_judged"]),
             r["human_verdict"], r["category"], r["replay"]),
        )
    for g in aggregates["groups"]:
        con.execute(
            "INSERT INTO aggregates VALUES (?,?,?,?,?,?,?)",
            (g["task_id"], g["model"], g["n"], g["successes"], g["success_rate"],
             g["median_steps"], int(g["ranked"])),
        )
    con.commit()
    con.close()
    return db


_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AnyGame-Bench results</title>
<style>
 body {{ font-family: Segoe UI, sans-serif; background: #141418; color: #ddd; margin: 24px; }}
 table {{ border-collapse: collapse; margin: 16px 0; width: 100%; }}
 th, td {{ border: 1px solid #333; padding: 6px 10px; text-align: left; }}
 th {{ background: #1d1d24; }}
 .unranked {{ color: #e5c07b; }}
 .ok {{ color: #98c379; }} .bad {{ color: #ff7b72; }} .part {{ color: #e5c07b; }}
 a {{ color: #61afef; }}
 h3 {{ margin-top: 28px; }}
</style></head><body>
<h2>AnyGame-Bench — results</h2>
<p>{total} runs · judge agreement: {judge_line}</p>
<h3>Per task × model</h3>
{group_table}
<h3>All runs</h3>
{run_table}
</body></html>"""


def write_html(runs_root: Path, rows: list[dict], aggregates: dict, judge: JudgeSummary) -> Path:
    def esc(v):
        return str(v).replace("<", "&lt;").replace(">", "&gt;")

    judge_line = (
        f"{judge.agreement} over {judge.n} (FP={judge.false_positive_rate} "
        f"FN={judge.false_negative_rate})" if judge.agreement is not None else "not calibrated"
    )

    group_rows = []
    for g in aggregates["groups"]:
        rank = "" if g["ranked"] else ' class="unranked" title="n < 5: not ranked"'
        note = "" if g["ranked"] else " (not ranked, n<5)"
        group_rows.append(
            f"<tr{rank}><td>{esc(g['task_id'])}</td><td>{esc(g['model'])}</td>"
            f"<td>{g['n']}{note}</td><td>{g['successes']}</td>"
            f"<td>{g['success_rate']:.0%}</td><td>{g['median_steps']:.0f}</td>"
            f"<td>{g['median_invalid']:.0%}</td><td>{g['judge_agreement'] or '-'}</td></tr>"
        )
    group_table = (
        "<table><tr><th>task</th><th>model</th><th>n</th><th>successes</th>"
        "<th>success rate</th><th>median steps</th><th>median invalid</th>"
        "<th>judge agreement</th></tr>" + "\n".join(group_rows) + "</table>"
    )

    run_rows = []
    for r in sorted(rows, key=lambda x: (x["task_id"], x["model"])):
        jcls = {"success": "ok", "fail": "bad", "partial": "part"}.get(
            r.get("judge_verdict") or "", "")
        run_rows.append(
            f"<tr><td>{esc(r['run_id'])}</td><td>{esc(r['task_id'])}</td>"
            f"<td>{esc(r['model'])}</td><td>{esc(r['outcome'])}</td>"
            f"<td>{r['steps']}</td><td>{r['invalid_rate']:.0%}</td>"
            f"<td class='{jcls}'>{esc(r.get('judge_verdict') or '-')}</td>"
            f"<td>{esc(r.get('human_verdict') or '-')}</td>"
            f"<td>{esc(r.get('category') or '-')}</td>"
            f"<td><a href='{esc(r['replay'])}'>replay</a></td></tr>"
        )
    run_table = (
        "<table><tr><th>run</th><th>task</th><th>model</th><th>outcome</th>"
        "<th>steps</th><th>invalid</th><th>judge</th><th>human</th>"
        "<th>category</th><th></th></tr>" + "\n".join(run_rows) + "</table>"
    )

    html = _HTML_TEMPLATE.format(
        total=aggregates["total_runs"], judge_line=judge_line,
        group_table=group_table, run_table=run_table,
    )
    out = Path(runs_root) / "report.html"
    out.write_text(html, encoding="utf-8")
    return out


def build_report(runs_root: str | Path) -> dict:
    """Full report pipeline: load, aggregate, sqlite, html. Returns the summary."""
    runs_root = Path(runs_root)
    rows = load_runs(runs_root)
    aggregates = aggregate(rows)
    judge = judge_summary(runs_root, rows)
    db = write_sqlite(runs_root, rows, aggregates)
    html = write_html(runs_root, rows, aggregates, judge)
    return {
        "total_runs": aggregates["total_runs"],
        "groups": aggregates["groups"],
        "judge": judge,
        "db": str(db),
        "html": str(html),
    }
