"""Report generation tests (headless, synthetic run folders)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agb.report import aggregate, build_report, judge_summary, load_runs


def _make_run(runs_root: Path, run_id: str, model: str, task: str, *,
              outcome: str = "claimed_done", success: bool = True,
              steps: int = 5, invalid: float = 0.1, judge: str | None = None,
              self_judged: bool = False, human: str | None = None,
              category: str | None = None, label_verdict: str | None = None) -> Path:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    d = {
        "run_id": run_id, "task_id": task, "model": model, "agent_mode": "A",
        "mode": "paused", "outcome": outcome, "success": success, "steps": steps,
        "invalid_rate": invalid, "invalid_actions": 0, "stuck_events": 0,
        "wall_seconds": 100.0, "avg_latency_ms": 20000, "tokens_in": 1000,
        "tokens_out": 50, "cost_usd": 0.0,
        "verdict": ({"verdict": judge, "confidence": 0.9,
                     "self_judged": self_judged} if judge else None),
    }
    (run_dir / "result.json").write_text(json.dumps(d), encoding="utf-8")
    if label_verdict:
        entry = {"run_id": run_id, "human": label_verdict, "category": category}
        (run_dir / "labels.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    (run_dir / "replay.html").write_text("<html>replay</html>", encoding="utf-8")
    return run_dir


class TestLoadRuns:
    def test_loads_with_labels_and_verdict(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", judge="success",
                  self_judged=True, label_verdict="success", category="none")
        rows = load_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0]["judge_verdict"] == "success"
        assert rows[0]["self_judged"] is True
        assert rows[0]["human_verdict"] == "success"
        assert rows[0]["category"] == "none"
        assert rows[0]["replay"].endswith("replay.html")

    def test_skips_dirs_without_results(self, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        assert load_runs(tmp_path) == []


class TestAggregate:
    def test_groups_and_rates(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", success=True, steps=4)
        _make_run(tmp_path, "r2", "m1", "task-a", success=False, steps=8)
        _make_run(tmp_path, "r3", "m2", "task-a", success=True, steps=2)
        agg = aggregate(load_runs(tmp_path))
        groups = {(g["task_id"], g["model"]): g for g in agg["groups"]}
        a = groups[("task-a", "m1")]
        assert a["n"] == 2 and a["successes"] == 1
        assert a["success_rate"] == 0.5
        assert a["median_steps"] == 6.0
        assert a["ranked"] is False  # n < 5: never ranked
        b = groups[("task-a", "m2")]
        assert b["n"] == 1 and b["ranked"] is False

    def test_failure_category_histogram(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", label_verdict="fail", category="grounding")
        _make_run(tmp_path, "r2", "m1", "task-a", label_verdict="fail", category="grounding")
        _make_run(tmp_path, "r3", "m1", "task-a", label_verdict="fail", category="timing")
        agg = aggregate(load_runs(tmp_path))
        g = agg["groups"][0]
        assert g["failure_categories"] == {"grounding": 2, "timing": 1}

    def test_judge_agreement_vs_human(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", judge="success", label_verdict="success")
        _make_run(tmp_path, "r2", "m1", "task-a", judge="fail", label_verdict="success")
        agg = aggregate(load_runs(tmp_path))
        assert agg["groups"][0]["judge_agreement"] == 0.5


class TestBuildReport:
    def test_full_pipeline(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", judge="success",
                  label_verdict="success", category="none")
        _make_run(tmp_path, "r2", "m1", "task-a", judge="fail",
                  label_verdict="fail", category="grounding")
        summary = build_report(tmp_path)

        assert summary["total_runs"] == 2
        assert len(summary["groups"]) == 1
        assert summary["judge"].agreement == 1.0
        assert Path(summary["db"]).exists()
        assert Path(summary["html"]).exists()

        con = sqlite3.connect(summary["db"])
        n = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert n == 2
        aggs = con.execute("SELECT task_id, model, n, ranked FROM aggregates").fetchall()
        assert aggs and all(row[3] == 0 for row in aggs)  # n<5: unranked
        con.close()

        html = Path(summary["html"]).read_text(encoding="utf-8")
        assert "task-a" in html and "replay" in html
        assert "not ranked" in html or "unranked" in html or 'class="unranked"' in html

    def test_judge_summary_from_calibration(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a")
        (tmp_path / "judge_calibration.json").write_text(json.dumps({
            "judge": "m1", "n": 30, "agreement": 0.839,
            "false_positive_rate": 0.032, "false_negative_rate": 0.129,
        }), encoding="utf-8")
        s = judge_summary(tmp_path, load_runs(tmp_path))
        assert s.agreement == 0.839 and s.n == 30
        assert s.false_positive_rate == 0.032


class TestEffectiveSuccess:
    def test_label_overrides_adapter_false(self, tmp_path):
        """Manual games: adapter success is always False; the label is truth."""
        _make_run(tmp_path, "r1", "m1", "task-a", success=False,
                  judge="success", label_verdict="success")
        rows = load_runs(tmp_path)
        assert rows[0]["effective_success"] is True
        agg = aggregate(rows)
        assert agg["groups"][0]["successes"] == 1

    def test_deterministic_success_wins_without_label(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", success=True, judge=None)
        rows = load_runs(tmp_path)
        assert rows[0]["effective_success"] is True

    def test_judge_used_when_no_label_or_adapter(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", success=False, judge="success")
        rows = load_runs(tmp_path)
        assert rows[0]["effective_success"] is True

    def test_judge_fail_stays_fail(self, tmp_path):
        _make_run(tmp_path, "r1", "m1", "task-a", success=False, judge="fail")
        rows = load_runs(tmp_path)
        assert rows[0]["effective_success"] is False
