"""Execute loop: observe -> decide -> act (architecture 6 step 3, guide 9).

The loop never trusts the agent: caps and the kill switch are checked around
every model call and action batch, invalid outputs are counted and re-asked
once, and stuck detection injects a fixed hint identical for every model.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field

from PIL import ImageDraw

from agb.agent.base import Agent, Decision
from agb.agent.parsing import extract_json_object, parse_model_output
from agb.agent.prompts import SYSTEM, build_user_message
from agb.capture import WindowCapture, ensure_foreground
from agb.inputs import WindowInput
from agb.killswitch import KillSwitch
from agb.models import TaskSpec

DEFAULT_SETTLE_MS = 300
DEFAULT_STUCK_PATIENCE = 5
_STUCK_PIXEL_THRESHOLD = 0.002  # fraction of sampled bytes that must change
_MAX_STORED_ERRORS = 10
_MAX_RAW_SAMPLES = 5
_RAW_SAMPLE_CHARS = 400
_MAX_WAIT_MS = 2000
_MODEL_ATTEMPTS = 2  # tries per model call (transient failures)
_MODEL_BACKOFF_S = 3.0
_MAX_CONSECUTIVE_MODEL_FAILURES = 3  # then abort with model_error

_CALIBRATION_PROMPT = (
    "A large magenta dot was drawn on this screenshot at a known position. "
    'Reply ONLY with JSON: {"center_x": <int>, "center_y": <int>} '
    "for the magenta dot center, in the same pixel coordinates you would use "
    "for click actions on this screenshot."
)


def _calibrate_frame(agent: Agent, view, res: LoopResult) -> tuple[float, float]:
    """Measure the model's coordinate frame with a dot at a known position.

    Some vision pipelines rescale images before the encoder, so the model
    reports coordinates in its own frame (measured ~1024x768 through Ollama);
    the measured ratio converts its coordinates back to ours.
    """
    try:
        w, h = view.size
        tx, ty = int(w * 0.75), int(h * 0.75)
        probe = view.copy()
        d = ImageDraw.Draw(probe)
        d.ellipse([tx - 14, ty - 14, tx + 14, ty + 14], fill=(255, 0, 255))
        buf = io.BytesIO()
        probe.save(buf, "JPEG", quality=85)
        decision = agent.decide(
            "You are a precise visual locator. Reply ONLY with JSON.",
            _CALIBRATION_PROMPT,
            [buf.getvalue()],
        )
        res.model_calls += 1
        _accumulate(res, decision.usage)
        obj = extract_json_object(decision.raw) or {}
        cx, cy = obj.get("center_x"), obj.get("center_y")
        # the model may emit the point as a pair in either field
        if isinstance(cx, (list, tuple)) and len(cx) == 2:
            cx, cy = cx[0], cx[1]
        elif isinstance(cy, (list, tuple)) and len(cy) == 2:
            cx, cy = cy[0], cy[1]
        if not isinstance(cx, (int, float)) or not isinstance(cy, (int, float)):
            raise ValueError(f"calibration reply unparsable: {decision.raw[:100]!r}")
        sx, sy = cx / tx, cy / ty
        if abs(sx - 1) < 0.05:
            sx = 1.0
        if abs(sy - 1) < 0.05:
            sy = 1.0
        sx, sy = min(max(sx, 0.4), 3.0), min(max(sy, 0.4), 3.0)
        return (sx, sy)
    except Exception as e:  # graceful: run unscaled if calibration fails
        _note_error(res, f"frame calibration failed: {e}")
        return (1.0, 1.0)


def _scale_action(a, sx: float, sy: float):
    """Convert model-frame coordinates to our view frame (in place)."""
    for f in ("x", "x1", "x2"):
        if getattr(a, f, None) is not None:
            setattr(a, f, int(round(getattr(a, f) / sx)))
    for f in ("y", "y1", "y2"):
        if getattr(a, f, None) is not None:
            setattr(a, f, int(round(getattr(a, f) / sy)))
    return a


@dataclass
class LoopResult:
    outcome: str  # claimed_done | cap_steps | cap_time | aborted | model_error
    steps: int = 0
    model_calls: int = 0
    invalid_outputs: int = 0  # model replies that failed tolerant parsing
    invalid_actions: int = 0  # actions rejected at execution time
    stuck_events: int = 0
    wall_seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latencies_ms: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_samples: list[str] = field(default_factory=list)  # first N raw replies
    frame_scale: tuple[float, float] | None = None  # measured model coordinate frame
    scratchpad: str = ""

    @property
    def invalid_rate(self) -> float:
        return self.invalid_outputs / self.model_calls if self.model_calls else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0


def _jpeg(img, quality: int = 80) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _sample(img, step: int = 12) -> bytes:
    return img.tobytes()[::step]


def _changed_frac(a: bytes | None, b: bytes) -> float:
    if a is None or not a or not b:
        return 1.0
    n = min(len(a), len(b))
    diff = sum(1 for x, y in zip(a[:n], b[:n], strict=False) if x != y)
    return diff / n


def _accumulate(res: LoopResult, usage: dict) -> None:
    res.tokens_in += int(usage.get("in_tokens", 0) or 0)
    res.tokens_out += int(usage.get("out_tokens", 0) or 0)
    res.cost_usd += float(usage.get("cost_usd", 0.0) or 0.0)
    lat = int(usage.get("latency_ms", 0) or 0)
    if lat:
        res.latencies_ms.append(lat)


_ACTION_DESC = {
    "click": "click", "double_click": "double_click", "drag": "drag",
    "move": "move", "key": "key", "type": "type", "scroll": "scroll",
    "wait": "wait", "note": "note", "done": "done",
}


def _note_error(res: LoopResult, msg: str) -> None:
    if len(res.errors) < _MAX_STORED_ERRORS:
        res.errors.append(msg)


def _call_agent(
    agent: Agent, system: str, user: str, images: list[bytes], res: LoopResult
) -> Decision | None:
    """Call the model with bounded retries on transient failures.

    Each attempt counts as a model call (metrics honesty). Returns None after
    the final failure; the loop aborts with model_error after repeated
    consecutive failures so a dead endpoint can never hang a run.
    """
    last_err = ""
    for attempt in range(_MODEL_ATTEMPTS):
        res.model_calls += 1
        try:
            return agent.decide(system, user, images)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            _note_error(res, f"model call failed: {last_err}")
            if attempt < _MODEL_ATTEMPTS - 1:
                time.sleep(_MODEL_BACKOFF_S * (attempt + 1))
    return None


def execute(
    task: TaskSpec,
    agent: Agent,
    capture: WindowCapture,
    inp: WindowInput,
    kill: KillSwitch,
    *,
    max_steps: int | None = None,
    max_wall_minutes: float | None = None,
    settle_ms: int = DEFAULT_SETTLE_MS,
    stuck_patience: int = DEFAULT_STUCK_PATIENCE,
) -> LoopResult:
    """Run the EXECUTE phase. Returns a LoopResult; judging happens elsewhere."""
    limits = task.limits
    steps_cap = max_steps if max_steps is not None else limits.max_steps
    wall_cap_s = (
        max_wall_minutes if max_wall_minutes is not None else limits.max_wall_minutes
    ) * 60

    res = LoopResult(outcome="cap_steps")
    scratchpad = ""
    recent: list[str] = []
    last_sample: bytes | None = None
    unchanged_steps = 0
    acted_last_step = False
    consecutive_model_failures = 0
    wants_calibration = getattr(agent, "frame_calibration", False)
    frame_scale: tuple[float, float] | None = (1.0, 1.0) if not wants_calibration else None
    t_start = time.perf_counter()

    for _step in range(steps_cap):
        if kill.tripped:
            res.outcome = "aborted"
            break
        if time.perf_counter() - t_start >= wall_cap_s:
            res.outcome = "cap_time"
            break

        # The game must be foreground or the capture sees whatever covers it.
        if not capture.win.isActive:
            ensure_foreground(capture.win)
            time.sleep(0.2)

        _full, view, scale, _ts = capture.grab()

        if frame_scale is None:
            frame_scale = _calibrate_frame(agent, view, res)
            res.frame_scale = frame_scale

        sample = _sample(view)
        changed = _changed_frac(last_sample, sample)
        last_sample = sample

        stuck_now = False
        if acted_last_step and changed < _STUCK_PIXEL_THRESHOLD:
            unchanged_steps += 1
            if unchanged_steps >= stuck_patience:
                stuck_now = True
                res.stuck_events += 1
                unchanged_steps = 0
        else:
            unchanged_steps = 0

        user = build_user_message(
            task.goal, scratchpad, recent, stuck=stuck_now, patience=stuck_patience
        )
        jpeg = _jpeg(view)
        decision = _call_agent(agent, SYSTEM, user, [jpeg], res)
        if decision is None:
            consecutive_model_failures += 1
            if consecutive_model_failures >= _MAX_CONSECUTIVE_MODEL_FAILURES:
                res.outcome = "model_error"
                break
            res.steps += 1
            recent.append("(model call failed)")
            acted_last_step = False
            continue
        consecutive_model_failures = 0
        _accumulate(res, decision.usage)
        if len(res.raw_samples) < _MAX_RAW_SAMPLES:
            res.raw_samples.append(decision.raw[:_RAW_SAMPLE_CHARS])

        if kill.tripped:
            res.outcome = "aborted"
            break

        thought, actions, err = parse_model_output(decision.raw)
        if err is not None:
            res.invalid_outputs += 1
            _note_error(res, err)
            # One re-ask with the error fed back (architecture 10, output reliability).
            user2 = (
                user + f"\n\nYour previous reply was not usable ({err}). "
                "Reply ONLY with the JSON object."
            )
            decision = _call_agent(agent, SYSTEM, user2, [jpeg], res)
            if decision is None:
                res.steps += 1
                recent.append("(invalid output)")
                acted_last_step = False
                continue
            _accumulate(res, decision.usage)
            thought, actions, err = parse_model_output(decision.raw)
            if err is not None:
                res.invalid_outputs += 1
                _note_error(res, err)
                res.steps += 1
                recent.append("(invalid output)")
                acted_last_step = False
                continue

        step_acted = False
        done = False
        for a in actions:
            kind = a.type
            if kind == "done":
                done = True
                break
            if kind == "note":
                scratchpad = a.text
                recent.append(f"note: {a.text[:40]}")
                continue
            if kind == "wait":
                time.sleep(min(a.ms, _MAX_WAIT_MS) / 1000)
                continue
            try:
                if kind in ("click", "double_click", "move", "drag", "scroll"):
                    a = _scale_action(a, *frame_scale)
                if kind == "click":
                    inp.click(a.x, a.y, scale, a.button)
                elif kind == "double_click":
                    inp.double_click(a.x, a.y, scale)
                elif kind == "move":
                    inp.move(a.x, a.y, scale)
                elif kind == "drag":
                    inp.drag(a.x1, a.y1, a.x2, a.y2, scale)
                elif kind == "key":
                    inp.key(a.key, a.hold_ms)
                elif kind == "type":
                    inp.type_text(a.text)
                elif kind == "scroll":
                    inp.scroll(a.dy, a.x, a.y, scale)
                else:  # pragma: no cover - schema forbids other types
                    raise ValueError(f"unhandled action type {kind!r}")
                step_acted = True
            except Exception as e:  # counted, never hidden
                res.invalid_actions += 1
                _note_error(res, f"{_ACTION_DESC.get(kind, kind)} rejected: {e}")
                recent.append(f"{kind}: REJECTED")

        res.steps += 1
        acted_last_step = step_acted
        if done:
            res.outcome = "claimed_done"
            break
        recent.append(_describe(actions, step_acted))
        time.sleep(settle_ms / 1000)

    res.wall_seconds = time.perf_counter() - t_start
    res.scratchpad = scratchpad
    return res


def _describe(actions, step_acted: bool) -> str:
    kinds = [_ACTION_DESC.get(a.type, a.type) for a in actions]
    desc = ", ".join(kinds) if kinds else "(no actions)"
    return desc + ("" if step_acted else " (no screen input)")
