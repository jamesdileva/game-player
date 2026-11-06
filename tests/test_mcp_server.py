"""Mode B MCP server tests (headless: fake capture + recording input)."""

from __future__ import annotations

import json
import tempfile

import pytest
from tests.conftest import ROOT
from tests.fakes import FakeCapture, FakeGameHarness

from agb.mcp_server import ModeBSession, build_server
from agb.models import load_task_spec
from agb.recorder import Recorder


def _spec():
    return load_task_spec(ROOT / "tasks" / "testbed" / "click-the-red-square.yaml")


@pytest.fixture
def session():
    h = FakeGameHarness()
    rec = Recorder(tempfile.mkdtemp(prefix="agb-mcp-"))
    s = ModeBSession(
        spec=_spec(),
        capture=FakeCapture(),
        inp=h.inp,
        recorder=rec,
        keys_only=False,
        max_steps=5,
        max_wall_minutes=5.0,
    )
    yield s
    rec.close()


@pytest.fixture
def server(session):
    return build_server(session)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _payload(result):
    texts = [c.text for c in result.content if hasattr(c, "text")]
    assert texts, f"no text content in {result}"
    return json.loads(texts[0])


class TestModeBTools:
    def test_screenshot_returns_image_and_status(self, session, server):
        out = _run(server.call_tool("screenshot", {}))
        payload = _payload(out)
        assert "image_base64" in payload
        assert payload["width"] > 0
        assert payload["steps_left"] == 4  # 1 of 5 tool calls used
        assert session.tool_calls == 1

    def test_key_translates_through_dialect_map(self, session, server):
        session.key_map = {"a": "x"}
        out = _run(server.call_tool("key", {"name": "a"}))
        payload = _payload(out)
        assert payload["sent"] == "x"
        assert session.inp.keys[-1] == "x"

    def test_click_rejected_in_keys_only(self, session, server):
        session.keys_only = True
        out = _run(server.call_tool("click", {"x": 100, "y": 100}))
        payload = _payload(out)
        assert "keys-only" in payload["refused"]
        assert session.inp.clicks == []

    def test_step_cap_refuses_further_calls(self, session, server):
        session.max_steps = 1
        session.tool_calls = 1
        out = _run(server.call_tool("screenshot", {}))
        payload = _payload(out)
        assert "step cap" in payload["refused"]

    def test_done_ends_episode(self, session, server):
        out = _run(server.call_tool("done", {"claim": "file select reached"}))
        _payload(out)
        assert "done claimed" in session.check_caps()

    def test_note_round_trips_through_screenshot(self, session, server):
        _run(server.call_tool("note", {"text": "goblin on the left"}))
        out = _run(server.call_tool("screenshot", {}))
        assert _payload(out)["scratchpad"] == "goblin on the left"
