"""Mode A client for any OpenAI-compatible chat endpoint (implementation-guide 7).

One client covers OpenRouter, Ollama (/v1), LM Studio, and most vendor APIs.
Per-model settings live in models.yaml; API keys come from the environment.
"""

from __future__ import annotations

import base64
import time

import httpx

from agb.agent.base import Decision


class OpenAICompatAgent:
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        price_in: float = 0.0,  # USD per million tokens
        price_out: float = 0.0,
        timeout: float = 120.0,
        temperature: float = 0.3,
        max_tokens: int = 400,  # bound runaway generations (local models ramble)
        extra_body: dict | None = None,  # provider-specific fields, e.g. {"think": false}
        native_ollama: bool = False,  # use Ollama's /api/chat (needed for think:false)
        transport: httpx.BaseTransport | None = None,  # injectable for tests
    ):
        self.name = name
        self.model = model
        self.price_in, self.price_out = price_in, price_out
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body or {})
        self.native_ollama = native_ollama
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(
            base_url=base_url, timeout=timeout, headers=headers, transport=transport
        )
        self.temperature = temperature

    @staticmethod
    def _img(jpeg: bytes) -> dict:
        b64 = base64.b64encode(jpeg).decode()
        return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}

    def decide(self, system: str, user: str, images: list[bytes]) -> Decision:
        t0 = time.perf_counter()
        if self.native_ollama:
            return self._decide_native(system, user, images, t0)
        return self._decide_openai(system, user, images, t0)

    def _native_url(self) -> str:
        """Strip the OpenAI '/v1' suffix from the base URL for /api/chat."""
        base = str(self.client.base_url).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/api/chat"

    def _decide_native(self, system: str, user: str, images: list[bytes], t0: float) -> Decision:
        """Ollama's /api/chat: the OpenAI-compat layer ignores think:false for
        some models, leaving reasoning running until the token budget dies."""
        b64s = [base64.b64encode(j).decode() for j in images]
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {"num_predict": self.max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": b64s},
            ],
        }
        r = self.client.post(self._native_url(), json=body)
        r.raise_for_status()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        raw = data.get("message", {}).get("content") or ""
        in_tokens = int(data.get("prompt_eval_count", 0) or 0)
        out_tokens = int(data.get("eval_count", 0) or 0)
        cost = in_tokens / 1e6 * self.price_in + out_tokens / 1e6 * self.price_out
        return Decision(
            raw=raw,
            usage={
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost_usd": cost,
                "latency_ms": latency_ms,
            },
        )

    def _decide_openai(self, system: str, user: str, images: list[bytes], t0: float) -> Decision:
        content: list[dict] = [{"type": "text", "text": user}]
        content += [self._img(j) for j in images]
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        body.update(self.extra_body)
        r = self.client.post("/chat/completions", json=body)
        r.raise_for_status()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        data = r.json()
        usage = data.get("usage") or {}
        in_tokens = int(usage.get("prompt_tokens", 0) or 0)
        out_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = in_tokens / 1e6 * self.price_in + out_tokens / 1e6 * self.price_out
        raw = data["choices"][0]["message"].get("content") or ""
        return Decision(
            raw=raw,
            usage={
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cost_usd": cost,
                "latency_ms": latency_ms,
            },
        )
