"""Scripted mock agent: cost-free orchestration tests (implementation-guide 13.5)."""

from __future__ import annotations

from agb.agent.base import Decision
from agb.models import Action


class ScriptedAgent:
    """Returns a queued list of actions per decide() call; zero API cost.

    Script entries are either a list of Actions (serialized to valid JSON) or
    a raw string (to test tolerant parsing). When the script is exhausted it
    emits a Wait, which lets cap and kill-switch tests run without hanging.
    """

    name = "scripted-mock"

    def __init__(self, script: list[list[Action] | str]):
        self._script = list(script)

    def decide(self, system: str, user: str, images: list[bytes]) -> Decision:
        if self._script:
            item = self._script.pop(0)
            raw = item if isinstance(item, str) else json_dumps_actions(item)
        else:
            raw = '{"thought": "script exhausted", "actions": [{"type": "wait", "ms": 100}]}'
        return Decision(
            raw=raw,
            usage={"in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0, "latency_ms": 0},
        )


def json_dumps_actions(actions: list[Action]) -> str:
    import json

    return json.dumps(
        {"thought": "scripted", "actions": [a.model_dump(exclude_defaults=False) for a in actions]}
    )
