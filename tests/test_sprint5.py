"""Sprint 5 tests: OSRS adapter semantics, label categories, matrix summary."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agb.cli import FAILURE_CATEGORIES, app, summarize_matrix

runner = CliRunner()


class TestOsrsAdapter:
    def test_window_title(self):
        from adapters import get_adapter

        assert get_adapter("osrs").WINDOW_TITLE == "RuneScape"

    def test_launch_raises_helpful_error(self):
        from adapters import get_adapter

        with pytest.raises(RuntimeError, match="manual game"):
            get_adapter("osrs").launch()

    def test_close_all_is_a_noop(self):
        """The user's logged-in client must never be closed."""
        from adapters import get_adapter

        get_adapter("osrs").close_all()  # must not raise

    def test_no_deterministic_state(self, tmp_path):
        from adapters import get_adapter

        adapter = get_adapter("osrs")
        state = adapter.read_state("RuneScape")
        assert state.get("stage") is None
        assert adapter.check_success(_osrs_task(), state) is False
        assert adapter.verify(_osrs_task(), state) is None


def _osrs_task():
    from agb.models import TaskSpec

    return TaskSpec.model_validate(
        {"id": "osrs-kill-goblin-001", "game": "osrs", "goal": "g",
         "success": {"evidence": "e"}}
    )


class TestLabelCategories:
    def test_label_writes_category(self, tmp_path):
        result = runner.invoke(
            app, ["label", str(tmp_path), "fail", "--category", "grounding"]
        )
        assert result.exit_code == 0
        entry = json.loads((tmp_path / "labels.jsonl").read_text(encoding="utf-8"))
        assert entry["human"] == "fail"
        assert entry["category"] == "grounding"

    def test_rejects_unknown_category(self, tmp_path):
        result = runner.invoke(app, ["label", str(tmp_path), "fail", "--category", "bogus"])
        assert result.exit_code == 1
        assert FAILURE_CATEGORIES  # taxonomy list present and non-empty


class TestMatrixSummary:
    def _rec(self, model, success, steps, invalid_rate, avg_latency_ms):
        return {"model": model, "success": success, "steps": steps,
                "invalid_rate": invalid_rate, "avg_latency_ms": avg_latency_ms}

    def test_aggregates_per_model(self):
        records = [
            self._rec("a", True, 4, 0.1, 100),
            self._rec("a", False, 6, 0.3, 200),
            self._rec("b", True, 2, 0.0, 50),
        ]
        out = summarize_matrix(records)
        assert "a" in out and "b" in out

    def test_empty_records(self):
        assert "runs" in summarize_matrix([])
