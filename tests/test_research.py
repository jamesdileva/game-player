"""Research phase tests (headless, web mode fully mocked — no network)."""

from __future__ import annotations

from agb.agent.mock import ScriptedAgent
from agb.research import research

BRIEF_JSON = '{"subgoals": []}'  # planner-shaped; irrelevant here


class TestNoneMode:
    def test_brief_from_model_knowledge(self, tmp_path):
        agent = ScriptedAgent(["Move the mouse to the red square and click it."])
        r = research("Click the red square.", "fakegame", agent, "none", tmp_path)
        assert "red square" in r.brief
        assert r.mode == "none"
        assert r.seconds >= 0
        assert (tmp_path / "brief.md").exists()
        assert "red square" in (tmp_path / "brief.md").read_text(encoding="utf-8")

    def test_usage_counted(self, tmp_path):
        agent = ScriptedAgent(["brief text"])
        r = research("g", "fakegame", agent, "none", tmp_path)
        # ScriptedAgent reports zero usage; the structure is what matters
        assert r.usage["in_tokens"] == 0 and r.usage["out_tokens"] == 0


class TestProvidedMode:
    def test_no_model_calls_and_exact_copy(self, tmp_path):
        calls = []

        class CountingAgent(ScriptedAgent):
            def decide(self, system, user, images):
                calls.append(user)
                return super().decide(system, user, images)

        agent = CountingAgent(["should never be called"])
        r = research("g", "fakegame", agent, "provided", tmp_path,
                     provided_text="Click at (430, 330).")
        assert calls == []  # zero model calls
        assert r.brief == "Click at (430, 330)."
        assert r.usage == {"in_tokens": 0, "out_tokens": 0}

    def test_missing_provided_text_falls_back_with_error(self, tmp_path):
        agent = ScriptedAgent(["improvised brief"])
        r = research("g", "fakegame", agent, "provided", tmp_path, provided_text="")
        assert r.error and "no brief text" in r.error
        assert "improvised" not in r.brief  # brief is the fallback notice


class TestWebMode:
    def test_harness_driven_loop_with_mocks(self, tmp_path):
        """Model emits SEARCH, harness fetches via injected fakes, then briefs."""
        agent = ScriptedAgent([
            "SEARCH: fake game red square location",
            "The red square is at (430, 330) according to the fetched page.",
        ])
        searches, fetches = [], []

        def fake_search(q):
            searches.append(q)
            return ["http://example.test/wiki"]

        def fake_fetch(url):
            fetches.append(url)
            return "PAGE CONTENT: the square is at 430,330 in the fake game."

        r = research("Click the red square.", "fakegame", agent, "web", tmp_path,
                     search=fake_search, fetch=fake_fetch)
        assert searches == ["fake game red square location"]
        assert fetches == ["http://example.test/wiki"]
        assert "430" in r.brief
        assert (tmp_path / "brief.md").exists()

    def test_time_cap_stops_the_loop(self, tmp_path):
        agent = ScriptedAgent(["SEARCH: query"])  # always wants more search
        r = research("g", "fakegame", agent, "web", tmp_path,
                     max_minutes=0, search=lambda q: [], fetch=lambda u: "")
        assert r.seconds < 10  # capped immediately
