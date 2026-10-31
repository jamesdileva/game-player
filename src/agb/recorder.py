"""Run recorder: steps.jsonl, JPEG frames, independent ffmpeg video (architecture 5.10).

Everything is flushed per step so a crash mid-run leaves usable partial logs.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image

from agb.config import redact

_MAX_RAW_CHARS = 2000


class Recorder:
    """Writes one JSONL record per step plus the full-res frame it saw."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        (self.run_dir / "frames").mkdir(parents=True, exist_ok=True)
        self._steps = open(self.run_dir / "steps.jsonl", "a", encoding="utf-8")
        self._video: subprocess.Popen | None = None
        self._step = 0
        self._t0 = time.perf_counter()

    def log_step(self, record: dict[str, Any], frame: Image.Image | None) -> str | None:
        """Persist one step record; returns the frame path written (or None)."""
        frame_path = None
        if frame is not None:
            frame_path = f"frames/{self._step:06d}.jpg"
            frame.save(self.run_dir / frame_path, "JPEG", quality=80)
        record = dict(record)
        record["step"] = self._step
        record["t_wall"] = round(time.perf_counter() - self._t0, 3)
        record["frame"] = frame_path
        if "raw_reply" in record:
            record["raw_reply"] = redact(str(record["raw_reply"]))[:_MAX_RAW_CHARS]
        self._steps.write(json.dumps(record, default=str) + "\n")
        self._steps.flush()
        self._step += 1
        return frame_path

    def start_video(self, rect: dict, fps: int = 10) -> bool:
        """Independent screen recording of the window region (Sprint 2).

        Region-based: gdigrab's title match is exact and the title changes with
        game state, so we pin the rect at start. A window that MOVES mid-run
        drifts out of frame (steps.jsonl remains the source of truth).
        Best-effort: if ffmpeg is missing or fails, steps.jsonl still stands.
        """
        try:
            self._video = subprocess.Popen(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "gdigrab",
                    "-offset_x", str(rect["left"]), "-offset_y", str(rect["top"]),
                    "-video_size", f"{rect['width']}x{rect['height']}",
                    "-framerate", str(fps),
                    "-i", "desktop",
                    "-pix_fmt", "yuv420p", "-y",
                    str(self.run_dir / "run.mp4"),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._video = None
        return self._video is not None

    def stop_video(self) -> None:
        if self._video is None:
            return
        try:
            if self._video.stdin:
                self._video.stdin.write(b"q")  # graceful stop writes the mp4 index
                self._video.stdin.flush()
            self._video.wait(timeout=10)
        except Exception:
            self._video.kill()
        finally:
            self._video = None

    def close(self) -> None:
        self.stop_video()
        if not self._steps.closed:
            self._steps.flush()
            self._steps.close()
