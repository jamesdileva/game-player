"""Environment setup, model profiles, and shared configuration helpers."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()  # reads .env if present; never overrides real environment variables

_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def redact(text: str) -> str:
    """Scrub API-key-shaped strings and known secret env values before saving.

    Applied to anything written to disk (prompts, raw replies, logs).
    """
    if not text:
        return text
    text = _SK_PATTERN.sub("sk-***REDACTED***", text)
    for name, val in os.environ.items():
        if re.search(r"KEY|TOKEN|SECRET", name) and val and len(val) >= 8 and val in text:
            text = text.replace(val, f"***REDACTED:{name}***")
    return text


def ensure_dpi_awareness() -> None:
    """Per-monitor DPI awareness so window coords match physical pixels.

    Mismatched scaling is the most common capture/click bug (implementation-guide 15).
    Call once at process start, before any window enumeration or capture.
    """
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


class ModelProfile(BaseModel):
    base_url: str
    model: str
    api_key_env: str | None = None
    price_in: float = 0.0  # USD per million tokens
    price_out: float = 0.0
    vision: bool = True
    timeout: float = 120.0  # seconds per model call (local models need more)
    max_tokens: int = 400  # bounds output; thinking models need headroom
    # measure the model's coordinate frame (see loop._calibrate_frame)
    calibrate_frame: bool = False
    extra_body: dict = Field(default_factory=dict)  # provider-specific request fields
    native_ollama: bool = False  # use /api/chat with think:false (OpenAI layer ignores it)


def load_model_profiles(path: str | Path = "models.yaml") -> dict[str, ModelProfile]:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles", {})
    return {name: ModelProfile.model_validate(cfg) for name, cfg in profiles.items()}


def build_agent(name: str, profiles_path: str | Path = "models.yaml"):
    """Instantiate an OpenAICompatAgent from a models.yaml profile.

    API keys come from the environment only; a missing key is a hard error.
    """
    from agb.agent.openai_compat import OpenAICompatAgent

    profiles = load_model_profiles(profiles_path)
    if name not in profiles:
        raise KeyError(f"Unknown model profile {name!r}; available: {sorted(profiles)}")
    p = profiles[name]
    api_key = os.environ.get(p.api_key_env) if p.api_key_env else None
    if p.api_key_env and not api_key:
        raise RuntimeError(
            f"Env var {p.api_key_env!r} (needed by model profile {name!r}) is not set"
        )
    agent = OpenAICompatAgent(
        name=name,
        base_url=p.base_url,
        model=p.model,
        api_key=api_key,
        price_in=p.price_in,
        price_out=p.price_out,
        timeout=p.timeout,
        max_tokens=p.max_tokens,
        extra_body=p.extra_body,
        native_ollama=p.native_ollama,
    )
    agent.frame_calibration = p.calibrate_frame
    return agent
