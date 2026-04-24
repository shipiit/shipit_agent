"""Tests for the cost-aware routing engine."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from shipit_agent.routing import (
    CostRouter,
    DifficultyTier,
    Tier,
    classify_difficulty,
)


# ─────────────────────── classifier ───────────────────────


class TestClassifier:
    @pytest.mark.parametrize(
        "prompt",
        [
            "Hi",
            "What day is it?",
            "Say hello.",
            "",
        ],
    )
    def test_easy_by_default(self, prompt: str) -> None:
        assert classify_difficulty(prompt) == DifficultyTier.EASY

    @pytest.mark.parametrize(
        "prompt",
        [
            "write a quick helper function",
            "create a new endpoint",
            "search the codebase for todos",
            "fix the typo in the README",
        ],
    )
    def test_medium_when_verb_is_action(self, prompt: str) -> None:
        assert classify_difficulty(prompt) == DifficultyTier.MEDIUM

    @pytest.mark.parametrize(
        "prompt",
        [
            "Please refactor the auth module",
            "Architect the migration plan",
            "Do a security audit",
            "Investigate why the test flakes",
            "Plan the rollout",
            "Optimise the query",
        ],
    )
    def test_hard_when_high_effort_verb_present(self, prompt: str) -> None:
        assert classify_difficulty(prompt) == DifficultyTier.HARD

    def test_long_prompt_beats_short_keyword(self) -> None:
        prompt = "Say hi. " + ("padding " * 80)
        assert classify_difficulty(prompt) == DifficultyTier.HARD

    def test_code_fence_nudges_to_medium(self) -> None:
        prompt = "See this:\n```python\nprint(1)\n```"
        # Short, no hard keyword, has a code fence — medium.
        assert classify_difficulty(prompt) == DifficultyTier.MEDIUM


# ─────────────────────── router adapter ───────────────────────


@dataclass
class _FakeResponse:
    content: str = "ok"
    usage: dict[str, int] | None = None


class _StubLLM:
    def __init__(self, label: str, tokens: int = 100) -> None:
        self.label = label
        self.tokens = tokens
        self.calls = 0

    def complete(self, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        return _FakeResponse(
            content=f"{self.label}:{self.calls}", usage={"total_tokens": self.tokens}
        )

    def stream(self, messages, **kwargs):  # noqa: ANN001
        # Produce two events — the inner loop doesn't inspect them.
        self.calls += 1
        yield {"type": "text", "content": f"{self.label}-0"}
        yield {"type": "text", "content": f"{self.label}-1"}


@pytest.fixture
def router() -> CostRouter:
    return CostRouter(
        easy=Tier(llm=_StubLLM("haiku"), price_per_1k=0.25, name="haiku"),
        medium=Tier(llm=_StubLLM("sonnet"), price_per_1k=3.0, name="sonnet"),
        hard=Tier(llm=_StubLLM("opus"), price_per_1k=15.0, name="opus"),
    )


class TestCostRouter:
    def test_easy_prompt_routes_to_easy(self, router: CostRouter) -> None:
        llm, tier = router.route("Hi")
        assert tier == DifficultyTier.EASY
        assert llm.label == "haiku"

    def test_hard_prompt_routes_to_hard(self, router: CostRouter) -> None:
        llm, tier = router.route("Architect the migration plan")
        assert tier == DifficultyTier.HARD
        assert llm.label == "opus"

    def test_complete_forwards_to_tiered_llm(self, router: CostRouter) -> None:
        # Three different-difficulty prompts → three different LLMs called.
        router.complete([{"role": "user", "content": "Hi"}])
        router.complete([{"role": "user", "content": "write a function"}])
        router.complete(
            [{"role": "user", "content": "Please refactor the auth module"}]
        )
        assert router.report.tier_counts == {"easy": 1, "medium": 1, "hard": 1}

    def test_savings_report_accurate(self, router: CostRouter) -> None:
        # Each call is 100 tokens. If all routed to hard: 3 * 0.1 * 15 = $4.5.
        # Actual: 0.1*0.25 + 0.1*3 + 0.1*15 = 0.025 + 0.3 + 1.5 = $1.825 → 59.4%.
        router.complete([{"role": "user", "content": "Hi"}])
        router.complete([{"role": "user", "content": "write a function"}])
        router.complete([{"role": "user", "content": "refactor auth"}])
        assert round(router.report.estimated_dollars_spent, 4) == 1.825
        assert round(router.report.estimated_dollars_if_hardest, 4) == 4.5
        assert 58.0 < router.report.savings_pct < 61.0

    def test_force_tier_overrides_classifier(self) -> None:
        router = CostRouter(
            easy=Tier(llm=_StubLLM("h"), price_per_1k=0.25),
            medium=Tier(llm=_StubLLM("s"), price_per_1k=3.0),
            hard=Tier(llm=_StubLLM("o"), price_per_1k=15.0),
            force_tier=DifficultyTier.MEDIUM,
        )
        _, tier = router.route("refactor everything")  # would normally → hard
        assert tier == DifficultyTier.MEDIUM

    def test_custom_difficulty_fn_overrides_heuristic(self) -> None:
        def always_easy(_p: str) -> DifficultyTier:
            return DifficultyTier.EASY

        router = CostRouter(
            easy=Tier(llm=_StubLLM("h")),
            medium=Tier(llm=_StubLLM("s")),
            hard=Tier(llm=_StubLLM("o")),
            difficulty_fn=always_easy,
        )
        assert router.classify("refactor everything") == DifficultyTier.EASY

    def test_exception_in_classifier_falls_back_to_medium(self) -> None:
        def boom(_p: str) -> DifficultyTier:
            raise RuntimeError("down")

        router = CostRouter(
            easy=Tier(llm=_StubLLM("h")),
            medium=Tier(llm=_StubLLM("s")),
            hard=Tier(llm=_StubLLM("o")),
            difficulty_fn=boom,
        )
        assert router.classify("anything") == DifficultyTier.MEDIUM

    def test_missing_usage_doesnt_blow_up_accounting(self, router: CostRouter) -> None:
        # LLM response without a usage dict — router must still return it.
        class _NoUsage:
            def complete(self, messages, **kw):  # noqa: ANN001
                class R:
                    content = "ok"

                return R()

            def stream(self, messages, **kw):  # noqa: ANN001
                yield {"type": "text", "content": "x"}

        router.tiers[DifficultyTier.EASY].llm = _NoUsage()
        r = router.complete([{"role": "user", "content": "Hi"}])
        assert r.content == "ok"
        assert router.report.estimated_dollars_spent == 0.0

    def test_stream_forwards_events(self, router: CostRouter) -> None:
        events = list(router.stream([{"role": "user", "content": "Hi"}]))
        assert len(events) == 2
        assert events[0]["content"].startswith("haiku")

    def test_handles_dataclass_message_not_just_dict(self, router: CostRouter) -> None:
        @dataclass
        class Msg:
            role: str
            content: str

        router.complete([Msg(role="user", content="refactor this")])
        assert router.report.tier_counts.get("hard") == 1

    def test_report_to_dict_roundtrip(self, router: CostRouter) -> None:
        router.complete([{"role": "user", "content": "Hi"}])
        d = router.report.to_dict()
        assert d["tier_counts"]["easy"] == 1
        assert "savings_pct" in d
