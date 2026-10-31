"""Prompts for the Mode A agent loop (implementation-guide 7).

The stuck hint text is fixed here so every model sees identical wording.
"""

from __future__ import annotations

SYSTEM = """You control a computer to complete a goal in a video game, using only the screen.
You see screenshots of the game window and act with mouse and keyboard.
Reply ONLY with JSON: {"thought": "...", "actions": [ ... ]}
Each action is a JSON object. Examples:
{"type": "click", "x": 430, "y": 330}
{"type": "key", "key": "w", "hold_ms": 800}
{"type": "wait", "ms": 1000}
{"type": "note", "text": "checking the square"}
{"type": "done", "claim": "I clicked it."}
Available action types: click, double_click, drag, move, key, type, scroll, wait, note, done.
Optional fields: click/double_click/move take x and y (button for click);
drag takes x1, y1, x2, y2; type takes text; scroll takes x, y, dy.
Coordinates are pixels in the screenshot you see (origin top-left).
Use note to keep a scratchpad; it is shown back to you every step.
Send 1-3 actions per turn. Only call done when you believe the goal is met,
and be ready to show evidence on screen."""

STUCK_HINT = (
    "Your last {patience} actions did not change the screen. "
    "Try a different approach."
)


def build_user_message(
    goal: str,
    scratchpad: str = "",
    recent_actions: list[str] | None = None,
    stuck: bool = False,
    patience: int = 5,
) -> str:
    """Build the per-step user message: goal, scratchpad, recent outcomes."""
    parts = [f"GOAL: {goal}"]
    parts.append(f"SCRATCHPAD: {scratchpad if scratchpad.strip() else '(empty)'}")
    if recent_actions:
        parts.append("RECENT ACTIONS: " + "; ".join(recent_actions[-3:]))
    if stuck:
        parts.append("HINT: " + STUCK_HINT.format(patience=patience))
    parts.append(
        'Reply with JSON: {"thought": "...", "actions": [...]} for the screenshot below.'
    )
    return "\n".join(parts)
