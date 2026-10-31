"""Tolerant parsing tests: fences, prose, garbage."""

from __future__ import annotations

from agb.agent.parsing import parse_model_output


class TestValidOutput:
    def test_plain_json(self):
        thought, actions, err = parse_model_output(
            '{"thought": "I see a square", "actions": [{"type": "click", "x": 10, "y": 20}]}'
        )
        assert err is None
        assert thought == "I see a square"
        assert len(actions) == 1 and actions[0].x == 10

    def test_fenced_json(self):
        text = '```json\n{"thought": "t", "actions": [{"type": "wait", "ms": 100}]}\n```'
        thought, actions, err = parse_model_output(text)
        assert err is None
        assert actions[0].ms == 100

    def test_prose_around_json(self):
        text = 'Sure! Here is my plan:\n{"thought": "go", "actions": []}\nHope that helps!'
        thought, actions, err = parse_model_output(text)
        assert err is None
        assert thought == "go" and actions == []

    def test_thought_defaults_empty(self):
        thought, actions, err = parse_model_output('{"actions": []}')
        assert err is None and thought == "" and actions == []


class TestFunctionCallStrings:
    """Models copy prompt notation like click(430, 330); the parser tolerates it."""

    def test_click_positional(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": ["click(430, 330)"]}'
        )
        assert err is None
        assert actions[0].type == "click" and actions[0].x == 430 and actions[0].y == 330
        assert actions[0].button == "left"

    def test_click_with_keyword_button(self):
        raw = "{\"thought\": \"t\", \"actions\": [\"click(430, 330, button='right')\"]}"
        _, actions, err = parse_model_output(raw)
        assert err is None
        assert actions[0].button == "right"

    def test_key_with_hold(self):
        _, actions, err = parse_model_output('{"thought": "t", "actions": ["key(w, 800)"]}')
        assert err is None
        assert actions[0].key == "w" and actions[0].hold_ms == 800

    def test_done_keeps_commas_and_parens(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": ["done(I killed it, finally)"]}'
        )
        assert err is None
        assert actions[0].claim == "I killed it, finally"

    def test_note_keeps_text(self):
        _, actions, err = parse_model_output('{"thought": "t", "actions": ["note(hello world)"]}')
        assert err is None
        assert actions[0].text == "hello world"

    def test_quoted_claim_unquoted(self):
        raw = r'{"thought": "t", "actions": ["done(\"I did it\")"]}'
        _, actions, err = parse_model_output(raw)
        assert err is None
        assert actions[0].claim == "I did it"

    def test_bare_done_string(self):
        _, actions, err = parse_model_output('{"thought": "t", "actions": ["done"]}')
        assert err is None
        assert actions[0].type == "done"

    def test_multi_object_reply_merges_actions(self):
        """Models plan whole turns as several JSON objects; actions merge."""
        text = (
            '{"type": "click", "x": 559, "y": 422}\n'
            '{"type": "wait", "ms": 1000}\n'
            '{"type": "click", "x": 559, "y": 422}\n'
            '{"thought": "going for the door", "actions": [{"type": "done", "claim": "ok"}]}'
        )
        thought, actions, err = parse_model_output(text)
        assert err is None
        assert len(actions) == 4
        assert actions[0].type == "click" and actions[-1].type == "done"
        assert "door" in thought

    def test_stray_trailing_brace_is_counted_invalid(self):
        """Unrecoverable brace soup counts as invalid, never crashes the loop."""
        _, _, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": [560, 430]}}'
        )
        assert err is not None

    def test_unrecognizable_string_still_invalid(self):
        _, _, err = parse_model_output('{"thought": "t", "actions": ["wave hello"]}')
        assert err is not None and err.startswith("invalid_action")


class TestNumericCoercion:
    """Models emit coordinates as strings or floats; intent is unambiguous."""

    def test_string_coords(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": "430", "y": " 330 "}]}'
        )
        assert err is None
        assert (actions[0].x, actions[0].y) == (430, 330)

    def test_float_coords(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": 430.7, "y": 330.0}]}'
        )
        assert err is None
        assert (actions[0].x, actions[0].y) == (431, 330)

    def test_string_wait_ms(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "wait", "ms": "1000"}]}'
        )
        assert err is None
        assert actions[0].ms == 1000

    def test_non_numeric_string_still_invalid(self):
        _, _, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": "left side", "y": 5}]}'
        )
        assert err is not None


class TestListCoordinates:
    """Models sometimes shove both coordinates into x as a list."""

    def test_list_x_without_y(self):
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": [557, 417]}]}'
        )
        assert err is None
        assert (actions[0].x, actions[0].y) == (557, 417)

    def test_list_x_with_separate_y(self):
        """Pair-in-x wins: the separate y field is noise (verified vs scalar replies)."""
        _, actions, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "click", "x": [556, 421], "y": 514}]}'
        )
        assert err is None
        assert (actions[0].x, actions[0].y) == (556, 421)

    def test_extract_json_object(self):
        from agb.agent.parsing import extract_json_object

        assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
        assert extract_json_object('blah {"a": {"b": 2}} blah') == {"a": {"b": 2}}
        assert extract_json_object("no json") is None


class TestInvalidOutput:
    def test_no_json_at_all(self):
        thought, actions, err = parse_model_output("I clicked the thing!")
        assert err == "no_json" and actions == []

    def test_unparseable_json(self):
        thought, actions, err = parse_model_output('{"thought": "x", "actions": [}')
        assert err == "no_json"

    def test_unknown_action_type(self):
        _, _, err = parse_model_output(
            '{"thought": "t", "actions": [{"type": "teleport", "x": 1, "y": 2}]}'
        )
        assert err is not None and err.startswith("invalid_action")

    def test_actions_not_a_list(self):
        _, _, err = parse_model_output('{"thought": "t", "actions": {"type": "click"}}')
        assert err == "actions_not_a_list"

    def test_missing_coords(self):
        _, _, err = parse_model_output('{"thought": "t", "actions": [{"type": "click"}]}')
        assert err is not None and err.startswith("invalid_action")

    def test_fenced_json_preferred_over_prose_braces(self):
        text = 'A {not json} then ```json\n{"thought": "real", "actions": []}\n```'
        thought, _, err = parse_model_output(text)
        assert err is None and thought == "real"
