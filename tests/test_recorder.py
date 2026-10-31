"""Recorder and redaction tests (headless)."""

from __future__ import annotations

import json

from PIL import Image

from agb.config import redact
from agb.recorder import Recorder


class TestRecorder:
    def test_step_records_and_frames(self, tmp_path):
        rec = Recorder(tmp_path)
        img = Image.new("RGB", (80, 60), (200, 30, 30))
        p1 = rec.log_step({"phase": "execute", "thought": "t1", "actions": [],
                           "usage": {"in_tokens": 1}, "raw_reply": "x", "error": None}, img)
        p2 = rec.log_step({"phase": "execute", "thought": "t2", "actions": [],
                           "usage": {}, "raw_reply": "", "error": None}, img)
        rec.close()

        assert p1 == "frames/000000.jpg" and p2 == "frames/000001.jpg"
        assert (tmp_path / "steps.jsonl").exists()
        lines = (tmp_path / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
        recs = [json.loads(line) for line in lines]
        assert [r["step"] for r in recs] == [0, 1]
        assert recs[0]["frame"] == "frames/000000.jpg"
        assert recs[0]["t_wall"] >= 0
        assert (tmp_path / "frames" / "000000.jpg").exists()

    def test_truncated_tail_still_parses(self, tmp_path):
        """A crash mid-write leaves a partial line; everything before is usable."""
        rec = Recorder(tmp_path)
        rec.log_step({"phase": "execute", "thought": "ok", "actions": [], "usage": {}}, None)
        rec.close()
        with open(tmp_path / "steps.jsonl", "a", encoding="utf-8") as f:
            f.write('{"step": 1, "thought": "trunc')  # simulate crash mid-write
        lines = (tmp_path / "steps.jsonl").read_text(encoding="utf-8").splitlines()
        parsed = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        assert len(parsed) == 1 and parsed[0]["thought"] == "ok"

    def test_raw_reply_redacted_on_save(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "supersecretvalue12345")
        rec = Recorder(tmp_path)
        rec.log_step({"phase": "execute", "thought": "t", "actions": [],
                      "usage": {}, "raw_reply": "my key is supersecretvalue12345 ok",
                      "error": None}, None)
        rec.close()
        text = (tmp_path / "steps.jsonl").read_text(encoding="utf-8")
        assert "supersecretvalue12345" not in text
        assert "REDACTED:OPENROUTER_API_KEY" in text


class TestRedact:
    def test_sk_pattern(self):
        out = redact("using sk-abcdef1234567890xyz today")
        assert "sk-abcdef1234567890xyz" not in out
        assert "sk-***REDACTED***" in out

    def test_env_key_value(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "tokenvalue123456")
        assert "tokenvalue123456" not in redact("auth: tokenvalue123456 done")

    def test_plain_text_untouched(self):
        assert redact("no secrets here") == "no secrets here"
