"""Replay viewer: a self-contained HTML page per run folder (Sprint 2).

The page embeds steps.jsonl and references the frames/ folder, so any run can
be replayed visually from its folder alone (Sprint 2 exit criterion 1).
"""

from __future__ import annotations

import json
from pathlib import Path

_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>agb replay</title>
<style>
 body {{ font-family: Consolas, monospace; background: #141418; color: #ddd;
        margin: 16px; }}
 img {{ max-width: 100%; border: 1px solid #333; image-rendering: pixelated; }}
 .info {{ white-space: pre-wrap; background: #1d1d24; padding: 10px;
          border-radius: 6px; min-height: 90px; }}
 input {{ width: 100%; }}
 .err {{ color: #ff7b72; }}
</style></head><body>
<h3>agb replay</h3>
<img id="f" src="">
<div class="info" id="i">(no steps)</div>
<input id="s" type="range" min="0" max="0" value="0" oninput="show(this.value)">
<script>
const steps = {steps_json};
const missing = {missing_json};
function fmt(a) {{ return (a.actions||[]).map(x =>
  x.type + "(" + ["x","y","x1","y1","x2","y2","key","text","claim","button",
    "hold_ms","ms","dy"].filter(k => x[k] !== undefined)
    .map(k => k + "=" + x[k]).join(", ") + ")").join("; ") || "(none)"; }}
function show(n) {{
  const s = steps[n];
  if (!s) {{ document.getElementById("f").src = ""; return; }}
  document.getElementById("f").src = s.frame;
  document.getElementById("i").textContent =
    "step " + s.step + "  t=" + s.t_wall + "s" + (s.error ? "  [ERROR: " + s.error + "]" : "")
    + "\\nusage: " + JSON.stringify(s.usage) + "\\nthought: " + (s.thought || "(none)")
    + "\\nactions: " + fmt(s) + "\\nraw: " + (s.raw_reply || "").slice(0, 400);
  document.getElementById("s").value = n;
}}
const slider = document.getElementById("s");
slider.max = steps.length - 1;
if (missing.length) {{
  const d = document.createElement("div");
  d.className = "err"; d.textContent = "missing frames: " + missing.join(", ");
  document.body.appendChild(d);
}}
show(0);
</script></body></html>"""


def generate(run_dir: str | Path) -> Path:
    """Write replay.html into the run folder; returns its path."""
    run_dir = Path(run_dir)
    steps: list[dict] = []
    missing: list[str] = []
    steps_file = run_dir / "steps.jsonl"
    if steps_file.exists():
        for line in steps_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # crash-truncated tail: replay what parsed
            frame = rec.get("frame")
            if frame and not (run_dir / frame).exists():
                missing.append(frame)
                rec["frame"] = ""
            steps.append(rec)
    html = _TEMPLATE.format(steps_json=json.dumps(steps), missing_json=json.dumps(missing))
    out = run_dir / "replay.html"
    out.write_text(html, encoding="utf-8")
    return out
