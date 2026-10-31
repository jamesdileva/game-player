"""Tolerant action parsing (implementation-guide 7, architecture 10).

Weak models produce malformed output; we extract what we can and report the
rest as counted errors. Handles code fences and surrounding prose.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from agb.models import Action, parse_actions

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_CALL_RE = re.compile(r"\s*([a-z_]+)\s*\((.*)\)\s*", re.DOTALL)

# positional parameter order per action type, for function-call syntax
_POSITIONAL_ARGS = {
    "click": ("x", "y", "button"),
    "double_click": ("x", "y"),
    "move": ("x", "y"),
    "drag": ("x1", "y1", "x2", "y2"),
    "key": ("key", "hold_ms"),
    "type": ("text",),
    "scroll": ("x", "y", "dy"),
    "wait": ("ms",),
    "note": ("text",),
    "done": ("claim",),
}

_INT_FIELDS = {"x", "y", "x1", "y1", "x2", "y2", "hold_ms", "ms", "dy"}


def _coerce_ints(action: dict) -> dict:
    """Coerce numeric fields given as strings or floats ("430", 430.7 -> 430)."""
    for k in action.keys() & _INT_FIELDS:
        v = action[k]
        if isinstance(v, str):
            try:
                action[k] = int(float(v.strip()))
            except ValueError:
                pass  # left as-is; validation reports the error
        elif isinstance(v, float):
            action[k] = int(round(v))
    return action


def _coerce_value(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        return v


def _coerce_action(a):
    """Accept function-call strings like 'click(430, 330)' as well as dicts.

    Models copy the action notation from prompts; tolerant parsing means
    counting real intent instead of rejecting on a syntax technicality.
    """
    if isinstance(a, str):
        bare = a.strip()
        if bare in _POSITIONAL_ARGS:  # bare "done" / "wait" with defaults
            return {"type": bare}
        m = _CALL_RE.match(a)
        if not m or m.group(1) not in _POSITIONAL_ARGS:
            return a  # left as-is; validation reports the error
        name, argstr = m.group(1), m.group(2).strip()
        params = _POSITIONAL_ARGS[name]
        if len(params) == 1:  # single text argument: keep commas and parens intact
            return {"type": name, params[0]: _coerce_value(argstr)}
        out: dict = {"type": name}
        pos = 0
        for part in (s.strip() for s in argstr.split(",")):
            if not part:
                continue
            key, sep, val = part.partition("=")
            if sep and key.strip() in params:
                out[key.strip()] = _coerce_value(val)
            elif pos < len(params):
                out[params[pos]] = _coerce_value(part)
                pos += 1
        return _coerce_ints(out)
    if isinstance(a, dict):
        # models often emit the point as a pair in x ("x": [556, 421]); the
        # separate y field is then noise — the pair wins (verified against
        # valid scalar replies aiming at the same spot)
        x = a.get("x")
        if isinstance(x, (list, tuple)) and len(x) == 2:
            a = dict(a)
            a["x"] = x[0]
            a["y"] = x[1]
        return _coerce_ints(a)
    return a


def extract_json_object(text: str) -> dict | None:
    """First valid JSON object in the text (fenced or brace-delimited), or None."""
    for span in _balanced_objects(text):
        try:
            obj = json.loads(span)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _balanced_objects(text: str) -> list[str]:
    """All top-level balanced {...} spans, fence-safe and stray-brace-safe."""
    spans: list[str] = []
    depth, start, in_str, esc = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append(text[start : i + 1])
                    start = -1
    return spans


_MAX_MERGED_ACTIONS = 8  # the model may plan its whole turn as several objects


def parse_model_output(text: str) -> tuple[str, list[Action], str | None]:
    """Extract (thought, actions, error) from a model reply.

    Models emit several JSON objects in one reply (one per intended turn);
    their actions are merged. Returns error=None on success. On failure,
    error names the problem so the loop can re-ask once with feedback.
    """
    spans = _balanced_objects(text)
    thoughts: list[str] = []
    raw_actions: list = []
    parsed_any = False
    saw_actions = False
    for span in spans:
        try:
            obj = json.loads(span)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        parsed_any = True
        if "thought" in obj:
            thoughts.append(str(obj["thought"]))
        if "actions" in obj:
            raw = obj["actions"]
            if not isinstance(raw, list):
                return " ".join(thoughts), [], "actions_not_a_list"
            saw_actions = True
            raw_actions.extend(raw)
        elif "type" in obj:  # a bare action object, not a wrapper
            raw_actions.append(obj)
            saw_actions = True
        if len(raw_actions) >= _MAX_MERGED_ACTIONS:
            break
    if not parsed_any:
        return "", [], "no_json"
    if not saw_actions:
        return " ".join(thoughts), [], "no_actions"
    try:
        actions = parse_actions([_coerce_action(a) for a in raw_actions])
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", []))
        return " ".join(thoughts), [], f"invalid_action {loc}: {first.get('msg')}"
    return " ".join(thoughts), actions, None
