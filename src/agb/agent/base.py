"""Agent protocol and shared result types (architecture.md 5.5, Mode A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Decision:
    """Raw model output plus usage accounting.

    Parsing into actions happens in the loop (agent/parsing.py), so every
    invalid output can be counted, never hidden.
    """

    raw: str
    # usage keys: in_tokens, out_tokens, cost_usd, latency_ms
    usage: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Anything that can look at images and emit text can be benchmarked."""

    name: str

    def decide(self, system: str, user: str, images: list[bytes]) -> Decision: ...
