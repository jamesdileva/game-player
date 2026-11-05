"""Reflex mode tests: one-line parsing, tiny prompts, plan skipping."""

from __future__ import annotations

from agb.agent.reflex import REFLEX_SYSTEM, build_reflex_message, parse_reflex


class TestParseReflex:
    def test_key(self):
        actions, err = parse_reflex("KEY enter")
        assert err is None and actions[0].type == "key" and actions[0].key == "enter"

    def test_key_case_insensitive(self):
        actions, err = parse_reflex("key down")
        assert err is None and actions[0].key == "down"

    def test_click(self):
        actions, err = parse_reflex("CLICK 430 330")
        assert err is None and (actions[0].x, actions[0].y) == (430, 330)

    def test_mark(self):
        actions, err = parse_reflex("MARK 2")
        assert err is None and actions[0].mark == 2

    def test_done_with_claim(self):
        actions, err = parse_reflex("DONE reached file select")
        assert err is None and actions[0].type == "done"
        assert actions[0].claim == "reached file select"

    def test_garbage_rejected(self):
        _, err = parse_reflex("I think I should press enter now.")
        assert err == "no_input_line"

    def test_key_without_name(self):
        _, err = parse_reflex("KEY")
        assert err == "key_missing_name"

    def test_system_prompt_is_tiny(self):
        assert len(REFLEX_SYSTEM) < 400  # bursty: the whole contract is tiny


class TestReflexMessage:
    def test_includes_goal_and_screen(self):
        msg = build_reflex_message("reach file select", ["New Game", "Continue"], [])
        assert "GOAL: reach file select" in msg
        assert "New Game" in msg

    def test_recent_capped_at_two(self):
        msg = build_reflex_message("g", [], ["KEY down", "KEY x", "KEY left"])
        assert "KEY down" not in msg and "KEY x" in msg


class TestBareKeyReplies:
    def test_bare_enter(self):
        actions, err = parse_reflex("ENTER")
        assert err is None and actions[0].type == "key" and actions[0].key == "enter"

    def test_bare_lowercase(self):
        actions, err = parse_reflex("down")
        assert err is None and actions[0].key == "down"

    def test_unknown_word_still_rejected(self):
        _, err = parse_reflex("goblin")
        assert err == "no_input_line"
