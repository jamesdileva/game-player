"""Research phase (architecture 5.7): goal + game -> brief.md.

Three modes: `none` (model's own knowledge), `provided` (fixed human brief,
zero model calls), `web` (harness-driven search/fetch loop per guide 8).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from agb.config import redact

_SEARCH_RE = re.compile(r"SEARCH:\s*(.+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MAX_WEB_ITERATIONS = 5
_MAX_FETCH_CHARS = 3000


@dataclass
class ResearchResult:
    brief: str
    mode: str
    seconds: float
    usage: dict = field(default_factory=dict)
    error: str | None = None


def _default_search(query: str) -> list[str]:
    """Best-effort keyless search via DuckDuckGo's HTML endpoint."""
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=20)
        links = re.findall(r'href="[^"]*uddg=([^"&]+)', r.text)
        from urllib.parse import unquote

        return [unquote(link) for link in links[:3]]
    except Exception:
        return []


def _default_fetch(url: str) -> str:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True)
        text = _TAG_RE.sub(" ", r.text)
        return re.sub(r"\s+", " ", text)[:_MAX_FETCH_CHARS]
    except Exception:
        return ""


def _usage_of(decision) -> dict:
    return {
        "in_tokens": int(decision.usage.get("in_tokens", 0) or 0),
        "out_tokens": int(decision.usage.get("out_tokens", 0) or 0),
    }


def _add(dst: dict, src: dict) -> None:
    dst["in_tokens"] = dst.get("in_tokens", 0) + src.get("in_tokens", 0)
    dst["out_tokens"] = dst.get("out_tokens", 0) + src.get("out_tokens", 0)


def research(
    goal: str,
    game: str,
    agent,
    mode: str,
    run_dir: str | Path,
    *,
    max_minutes: int = 10,
    provided_text: str = "",
    search=None,
    fetch=None,
) -> ResearchResult:
    """Run the research phase and write brief.md into the run folder."""
    search = search or _default_search
    fetch = fetch or _default_fetch
    t0 = time.perf_counter()
    usage: dict = {"in_tokens": 0, "out_tokens": 0}
    error: str | None = None
    brief = ""

    if mode == "provided":
        if not provided_text.strip():
            error = "provided mode but no brief text found"
            brief = f"(no provided brief: {error})"
        else:
            brief = provided_text

    elif mode == "web":
        material = ""
        deadline = time.perf_counter() + max_minutes * 60
        for _ in range(_MAX_WEB_ITERATIONS):
            if time.perf_counter() >= deadline:
                break
            prompt = (
                f"GOAL: {goal}\nGAME: {game}\n"
                f"MATERIAL SO FAR:\n{material or '(nothing yet)'}\n\n"
                "If you need more information, reply with one line 'SEARCH: <query>'. "
                "If you have enough, reply with the complete brief."
            )
            d = agent.decide("You are a game researcher.", prompt, [])
            _add(usage, _usage_of(d))
            m = _SEARCH_RE.search(d.raw)
            if not m:
                brief = d.raw.strip()
                break
            query = m.group(1).strip()
            urls = search(query)
            page_text = "\n\n".join(fetch(u) for u in urls)
            material += f"\n[search: {query}]\n{page_text}"

    else:  # none
        d = agent.decide(
            "You are a game researcher.",
            f"GOAL: {goal}\nGAME: {game}\nWrite a concise brief from your own "
            "knowledge: controls, relevant mechanics, where to go and what to "
            "click, risks, and how to tell the goal is achieved.",
            [],
        )
        _add(usage, _usage_of(d))
        brief = d.raw.strip()

    seconds = time.perf_counter() - t0
    (Path(run_dir) / "brief.md").write_text(
        f"# Research brief ({mode})\n\n{redact(brief)}\n", encoding="utf-8"
    )
    return ResearchResult(brief=brief, mode=mode, seconds=seconds, usage=usage, error=error)
