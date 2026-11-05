"""Reflex agent mode: minimal prompts, one-line responses (bursty small outputs).

For tasks that only need the next input (menus, simple navigation). Cuts
generation from hundreds of tokens to ~10 - the dominant cost on slow
local models. Aligned with the hybrid experiment's reflex-module concept
(experiment-hybrid-agent.md): a fast lightweight loop instead of a
deliberating one.
"""

from __future__ import annotations

import re

from agb.models import Action, Click, Done, Key

REFLEX_SYSTEM = (
    "You control a game with single inputs. "
    "Reply with exactly ONE line and nothing else:\n"
    "KEY <key>          (e.g. KEY enter, KEY down, KEY x, KEY z)\n"
    "CLICK <x> <y>      (pixels in the screenshot)\n"
    "MARK <n>           (click cyan badge n, when badges are shown)\n"
    "DONE <what happened>"
)

_INPUT_RE = re.compile(
    r"^\s*(KEY|CLICK|MARK|DONE)\b[:\s]*(.*)$", re.IGNORECASE | re.DOTALL
)
_KNOWN_KEYS = {
    "enter", "return", "x", "z", "space", "esc", "tab", "shift", "ctrl",
    "up", "down", "left", "right", "w", "a", "s", "d", "q", "e", "r",
}


def parse_reflex(raw: str) -> tuple[list[Action], str | None]:
    """Parse a one-line reflex reply into actions; (actions, error)."""
    bare = (raw or "").strip().lower()
    if bare in _KNOWN_KEYS:  # models sometimes answer the bare key name
        return [Key(key=bare)], None
    m = _INPUT_RE.search(raw or "")
    if not m:
        return [], "no_input_line"
    verb, rest = m.group(1).upper(), m.group(2).strip()
    if verb == "KEY":
        name = rest.split()[0].strip() if rest else ""
        if not name:
            return [], "key_missing_name"
        return [Key(key=name.lower())], None
    if verb == "CLICK":
        nums = re.findall(r"-?\d+", rest)
        if len(nums) >= 2:
            return [Click(x=int(nums[0]), y=int(nums[1]))], None
        return [], "click_missing_coords"
    if verb == "MARK":
        nums = re.findall(r"\d+", rest)
        if not nums:
            return [], "mark_missing_number"
        return [Click(mark=int(nums[0]))], None
    # DONE
    return [Done(claim=rest[:200])], None


def build_reflex_message(goal: str, ocr_lines: list[str], recent: list[str]) -> str:
    """Tiny per-step user message: goal + what's on screen + last inputs."""
    parts = [f"GOAL: {goal}"]
    if ocr_lines:
        parts.append("ON SCREEN: " + " | ".join(ocr_lines[:8]))
    if recent:
        parts.append("LAST: " + "; ".join(recent[-2:]))
    parts.append("Next input:")
    return "\n".join(parts)
