"""Prompt builder tests."""

from __future__ import annotations

from agb.agent.prompts import STUCK_HINT, SYSTEM, build_user_message


def test_system_prompt_covers_contract():
    assert "JSON" in SYSTEM
    # exact JSON object examples (function-call notation caused 89% invalid outputs)
    assert '{"type": "click", "x": 430, "y": 330}' in SYSTEM
    assert "done" in SYSTEM and "note" in SYSTEM


def test_message_includes_goal_and_scratchpad():
    msg = build_user_message("Click the red square.", scratchpad="found the square")
    assert "GOAL: Click the red square." in msg
    assert "SCRATCHPAD: found the square" in msg
    assert "RECENT ACTIONS" not in msg


def test_empty_scratchpad_placeholder():
    msg = build_user_message("goal", scratchpad="")
    assert "SCRATCHPAD: (empty)" in msg


def test_recent_actions_capped_at_three():
    actions = [f"click({i}, 0)" for i in range(5)]
    msg = build_user_message("goal", recent_actions=actions)
    assert "click(0, 0)" not in msg  # oldest dropped
    assert "click(4, 0)" in msg  # newest kept


def test_stuck_hint_wording_is_fixed():
    msg = build_user_message("goal", stuck=True, patience=5)
    assert STUCK_HINT.format(patience=5) in msg
    # identical for any patience value formatting
    assert build_user_message("goal", stuck=True, patience=7) == build_user_message(
        "goal", stuck=True, patience=7
    )
