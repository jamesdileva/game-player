"""Mode B: MCP tool server (architecture 5.5).

The harness stops owning the loop: an external MCP client (another agent,
opencode, or this project's own ZCode session) drives the game through these
tools, and the harness records every call, enforces the caps, and judges the
recording afterwards - identical to Mode A.

Run with: agb serve <task.yaml> [--window-title ...] [--max-steps N]
Transport: stdio (MCP clients spawn this process).
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from agb.config import ensure_dpi_awareness
from agb.models import TaskSpec, load_task_spec


@dataclass
class ModeBSession:
    """Mode B episode state. Game wiring is LAZY: MCP clients (e.g. ZCode)
    spawn the server at app startup, long before the game window exists, so
    capture/input connect on the first tool call instead."""

    spec: TaskSpec
    window_title: str = ""
    view_max: tuple[int, int] = (384, 288)
    capture: object = None
    inp: object = None
    recorder: object = None
    wired: bool = False
    wire_error: str | None = None
    keys_only: bool = False
    controls_hint: str = ""
    key_map: dict | None = None
    max_steps: int = 30
    max_wall_minutes: float = 40.0
    t0: float = field(default_factory=time.perf_counter)
    tool_calls: int = 0
    scratchpad: str = ""
    done_claim: str | None = None

    def ensure_wired(self) -> str | None:
        """Connect capture/input on first use. Returns an error or None."""
        if self.wired:
            return None
        try:
            from adapters import get_adapter

            from agb.capture import WindowCapture
            from agb.inputs import WindowInput

            adapter = get_adapter(self.spec.game)
            vw, vh = self.view_max
            self.capture = WindowCapture(
                self.window_title or adapter.WINDOW_TITLE, max_w=vw, max_h=vh
            )
            self.inp = WindowInput(self.capture)
            self.keys_only = getattr(adapter, "KEYS_ONLY", False)
            self.controls_hint = getattr(adapter, "CONTROLS_HINT", "")
            self.key_map = getattr(adapter, "KEY_MAP", None)
            self.wired = True
            if self.recorder is not None:  # start the mp4 once we can aim it
                try:
                    self.recorder.start_video(self.capture.rect())
                except Exception:
                    pass
            return None
        except Exception as e:
            self.wire_error = f"game window not connected: {e}"
            return self.wire_error

    def steps_left(self) -> int:
        return max(0, self.max_steps - self.tool_calls)

    def wall_left(self) -> float:
        return max(0.0, self.max_wall_minutes * 60 - (time.perf_counter() - self.t0))

    def check_caps(self) -> str | None:
        """Returns a refusal reason when a cap is hit, else None."""
        if self.done_claim is not None:
            return f"episode over (done claimed: {self.done_claim})"
        if self.steps_left() <= 0:
            return "step cap reached"
        if self.wall_left() <= 0:
            return "wall-clock cap reached"
        return None


def build_server(session: ModeBSession) -> MCPServer:
    server = MCPServer("anygame-bench")

    @server.tool()
    def screenshot() -> dict:
        """Capture the current game screen.

        Returns the view as base64 JPEG plus its pixel size and the session
        status. Decide your next input from this image.
        """
        refusal = session.check_caps()
        if refusal:
            return {"refused": refusal}
        wire_err = session.ensure_wired()
        if wire_err:
            return {"refused": wire_err, "hint": "launch the game, then retry"}
        full, view, scale, _ts = session.capture.grab()
        session.tool_calls += 1
        session.recorder.log_step(
            {"phase": "screenshot", "thought": "", "actions": [],
             "usage": {"in_tokens": 0, "out_tokens": 0}, "raw_reply": "",
             "error": None, "frame_scale": scale},
            full,
        )
        buf = io.BytesIO()
        view.save(buf, "JPEG", quality=80)
        return {
            "image_base64": base64.b64encode(buf.getvalue()).decode(),
            "width": view.width,
            "height": view.height,
            "keys_only": session.keys_only,
            "controls_hint": session.controls_hint,
            "steps_left": session.steps_left(),
            "scratchpad": session.scratchpad,
        }

    @server.tool()
    def click(x: int, y: int) -> dict:
        """Click at view-space pixel coordinates. Rejected in keys-only games."""
        refusal = session.check_caps()
        if refusal:
            return {"refused": refusal}
        wire_err = session.ensure_wired()
        if wire_err:
            return {"refused": wire_err}
        if session.keys_only:
            session.tool_calls += 1
            session.recorder.log_step(
                {"phase": "execute", "thought": "", "actions": [],
                 "usage": {"in_tokens": 0, "out_tokens": 0}, "raw_reply": "",
                 "error": "keys-only game: pointer actions disabled"}, None)
            return {"refused": "keys-only game: use the key tool instead"}
        session.inp.click(x, y, 1.0)
        session.tool_calls += 1
        session.recorder.log_step(
            {"phase": "execute", "thought": "",
             "actions": [{"type": "click", "x": x, "y": y}],
             "usage": {"in_tokens": 0, "out_tokens": 0}, "raw_reply": "",
             "error": None}, None)
        return {"ok": True}

    @server.tool()
    def key(name: str, hold_ms: int = 0) -> dict:
        """Press a keyboard key (optionally held). Translated through the
        adapter's dialect map when one exists."""
        refusal = session.check_caps()
        if refusal:
            return {"refused": refusal}
        wire_err = session.ensure_wired()
        if wire_err:
            return {"refused": wire_err}
        key_name = name.lower()
        if session.key_map:
            key_name = session.key_map.get(key_name, key_name)
        session.inp.key(key_name, hold_ms)
        session.tool_calls += 1
        session.recorder.log_step(
            {"phase": "execute", "thought": "",
             "actions": [{"type": "key", "key": name, "hold_ms": hold_ms}],
             "usage": {"in_tokens": 0, "out_tokens": 0}, "raw_reply": "",
             "error": None}, None)
        return {"ok": True, "sent": key_name}

    @server.tool()
    def note(text: str) -> dict:
        """Keep a one-paragraph scratchpad note; returned with each screenshot."""
        session.scratchpad = text[:2000]
        return {"ok": True}

    @server.tool()
    def done(claim: str) -> dict:
        """Declare the goal accomplished. Ends the episode."""
        session.done_claim = claim
        session.recorder.log_step(
            {"phase": "evidence", "thought": "", "actions": [],
             "usage": {"in_tokens": 0, "out_tokens": 0}, "raw_reply": claim,
             "error": None}, None)
        return {"ok": True, "note": "episode over; the run will be judged"}

    @server.tool()
    def status() -> dict:
        """Session status: steps, wall time, caps, scratchpad."""
        return {
            "steps_used": session.tool_calls,
            "steps_left": session.steps_left(),
            "wall_left_s": round(session.wall_left(), 1),
            "scratchpad": session.scratchpad,
            "done_claim": session.done_claim,
        }

    return server


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_task_path(task_path: str | Path) -> Path:
    """Resolve a task path against the repo root when the relative path
    doesn't exist (MCP clients spawn us from THEIR working directory, so
    relative config paths land elsewhere - do not depend on cwd)."""
    p = Path(task_path)
    if p.exists():
        return p
    alt = _REPO_ROOT / task_path
    if alt.exists():
        return alt
    return p  # let load_task_spec raise the familiar error


def load_session(
    task_path: str | Path,
    window_title: str | None,
    max_steps: int | None,
    view_max: str = "384x288",
    recorder=None,
) -> ModeBSession:
    """Build a lazy Mode B session from a task spec (used by agb serve).

    The game is NOT contacted here: MCP servers start before the game runs,
    so capture/input connect on the first tool call.
    """
    ensure_dpi_awareness()
    vw, vh = (int(v) for v in view_max.lower().split("x"))
    return ModeBSession(
        spec=load_task_spec(_resolve_task_path(task_path)),
        window_title=window_title or "",
        view_max=(vw, vh),
        recorder=recorder,
        max_steps=max_steps or 30,
        max_wall_minutes=40.0,
    )


class _NullRecorder:
    """Stand-in when no recorder is wired (tests)."""

    def log_step(self, *a, **k):
        pass

    def close(self):
        pass

    def stop_video(self):
        pass
