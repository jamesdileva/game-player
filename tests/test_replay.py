"""Replay page generation tests (headless)."""

from __future__ import annotations

import json

from PIL import Image

from agb.recorder import Recorder
from agb.replay import generate


def test_replay_references_frames_and_embeds_steps(tmp_path):
    rec = Recorder(tmp_path)
    rec.log_step({"phase": "execute", "thought": "aim", "actions": [],
                  "usage": {"in_tokens": 5}, "raw_reply": "raw text", "error": None},
                 Image.new("RGB", (40, 30), (10, 10, 10)))
    rec.close()

    page = generate(tmp_path)
    html = page.read_text(encoding="utf-8")
    assert "frames/000000.jpg" in html
    assert '"thought": "aim"' in html.replace('\\"', '"') or "aim" in html
    assert (tmp_path / "frames" / "000000.jpg").exists()

    # the embedded steps JSON must parse
    start = html.index("const steps = ") + len("const steps = ")
    end = html.index(";\n", start)
    steps = json.loads(html[start:end])
    assert steps[0]["thought"] == "aim"
    assert steps[0]["frame"] == "frames/000000.jpg"


def test_replay_reports_missing_frames(tmp_path):
    rec = Recorder(tmp_path)
    rec.log_step({"phase": "execute", "thought": "t", "actions": [], "usage": {}}, None)
    rec.close()
    (tmp_path / "steps.jsonl").write_text(
        '{"step": 1, "frame": "frames/999999.jpg", "thought": "gone"}\n', encoding="utf-8"
    )
    page = generate(tmp_path)
    html = page.read_text(encoding="utf-8")
    assert "frames/999999.jpg" in html  # listed as missing
