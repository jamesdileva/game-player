"""Agent client tests: scripted mock plus OpenAI-compatible client over a mock transport.

No network, no API cost (AGENTS.md: never burn tokens on tests).
"""

from __future__ import annotations

import json

import httpx
import pytest

from agb.agent.mock import ScriptedAgent
from agb.agent.openai_compat import OpenAICompatAgent
from agb.models import Click


class TestScriptedAgent:
    def test_pops_script_in_order(self):
        agent = ScriptedAgent([[Click(x=1, y=2)], "raw string reply"])
        d1 = agent.decide("s", "u", [])
        first_action = json.loads(d1.raw)["actions"][0]
        assert first_action == {"type": "click", "x": 1, "y": 2, "button": "left"}
        d2 = agent.decide("s", "u", [])
        assert d2.raw == "raw string reply"

    def test_exhausted_script_returns_wait(self):
        agent = ScriptedAgent([])
        d = agent.decide("s", "u", [])
        assert json.loads(d.raw)["actions"] == [{"type": "wait", "ms": 100}]
        assert d.usage["cost_usd"] == 0.0


def _mock_transport(responses: list[dict]):
    """Transport serving canned /chat/completions replies; records requests."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        body = responses.pop(0)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler), seen


class TestOpenAICompatAgent:
    def test_decide_parses_reply_and_usage(self):
        transport, seen = _mock_transport(
            [
                {
                    "choices": [{"message": {"content": '{"thought": "ok", "actions": []}'}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                }
            ]
        )
        agent = OpenAICompatAgent(
            name="t", base_url="http://mock", model="test-model", api_key="sk-test",
            price_in=3.0, price_out=15.0, transport=transport,
        )
        d = agent.decide("sys", "hello", [b"fake-jpeg"])
        assert d.raw.startswith('{"thought"')
        assert d.usage["in_tokens"] == 100 and d.usage["out_tokens"] == 10
        assert d.usage["cost_usd"] == pytest.approx(100 / 1e6 * 3.0 + 10 / 1e6 * 15.0)
        assert d.usage["latency_ms"] >= 0

        body = seen[0]
        assert body["model"] == "test-model"
        content = body["messages"][1]["content"]
        assert content[0]["type"] == "text" and content[0]["text"] == "hello"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_sends_bearer_header_when_key_set(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

        agent = OpenAICompatAgent(
            name="t", base_url="http://mock", model="m", api_key="sk-secret",
            transport=httpx.MockTransport(handler),
        )
        agent.decide("s", "u", [])
        assert captured["auth"] == "Bearer sk-secret"

    def test_no_auth_header_without_key(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

        agent = OpenAICompatAgent(
            name="t", base_url="http://mock", model="m",
            transport=httpx.MockTransport(handler),
        )
        agent.decide("s", "u", [])
        assert captured["auth"] is None

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        agent = OpenAICompatAgent(
            name="t", base_url="http://mock", model="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(httpx.HTTPStatusError):
            agent.decide("s", "u", [])

    def test_native_ollama_path_maps_fields(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            # base_url ends in /v1; the native path must strip it
            assert str(request.url).endswith("http://localhost:11434/api/chat")
            assert body["think"] is False and body["stream"] is False
            assert body["options"]["num_predict"] == 400
            assert body["messages"][1]["images"] == ["YjY0Ynl0ZXM="]  # b64("b64bytes")
            return httpx.Response(200, json={
                "message": {"content": '{"center_x": 500, "center_y": 500}'},
                "prompt_eval_count": 100, "eval_count": 20,
            })

        agent = OpenAICompatAgent(
            name="t", base_url="http://localhost:11434/v1", model="qwen3-vl:2b",
            max_tokens=400, native_ollama=True,
            transport=httpx.MockTransport(handler),
        )
        d = agent.decide("sys", "find it", [b"b64bytes"])
        assert d.raw == '{"center_x": 500, "center_y": 500}'
        assert d.usage["in_tokens"] == 100 and d.usage["out_tokens"] == 20

    def test_missing_content_treated_as_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {}}]})

        agent = OpenAICompatAgent(
            name="t", base_url="http://mock", model="m",
            transport=httpx.MockTransport(handler),
        )
        d = agent.decide("s", "u", [])
        assert d.raw == ""
