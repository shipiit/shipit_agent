"""The default Bedrock model has prices, so a cost cap works with it.

A live run with max_budget_usd stopped after one step: shipit's default
model, bedrock/openai.gpt-oss-120b-1:0, had no row, and a budget without
pricing fails closed.
"""

from __future__ import annotations

import pytest

from shipit_agent.costs.pricing import MODEL_PRICING, resolve_pricing_key


@pytest.mark.parametrize(
    "model,key",
    [("bedrock/openai.gpt-oss-120b-1:0", "gpt-oss-120b"), ("openai.gpt-oss-20b-1:0", "gpt-oss-20b"),
     ("gpt-oss-120b", "gpt-oss-120b")],
)
def test_gpt_oss_ids_resolve_to_a_price(model: str, key: str) -> None:
    assert resolve_pricing_key(model, MODEL_PRICING) == key


def test_the_rates_are_per_million_tokens() -> None:
    assert MODEL_PRICING["gpt-oss-120b"] == {"input": 0.15, "output": 0.60}
    assert MODEL_PRICING["gpt-oss-20b"] == {"input": 0.07, "output": 0.30}


def test_a_budget_run_on_the_default_model_is_not_stopped_for_lack_of_prices() -> None:
    from shipit_agent import Agent
    from shipit_agent.llms.base import LLMResponse

    class _DefaultModel:
        model = "bedrock/openai.gpt-oss-120b-1:0"

        def complete(self, **_: object) -> LLMResponse:
            return LLMResponse(content="done", usage={"prompt_tokens": 3000, "completion_tokens": 80, "total_tokens": 3080})

    result = Agent(llm=_DefaultModel(), max_budget_usd=0.25).run("hi")
    assert result.subtype == "success" and result.total_cost_usd and result.total_cost_usd > 0


@pytest.mark.parametrize(
    "model,key",
    [("google.gemma-4-31b", "google.gemma-4-31b"), ("bedrock/google.gemma-4-31b", "google.gemma-4-31b"),
     ("bedrock_mantle/google.gemma-4-31b", "google.gemma-4-31b"),
     ("google.gemma-4-26b-a4b", "google.gemma-4-26b-a4b"),
     ("bedrock_mantle/google.gemma-4-26b-a4b", "google.gemma-4-26b-a4b")],
)
def test_gemma_4_on_bedrock_mantle_resolves_to_a_price(model: str, key: str) -> None:
    assert resolve_pricing_key(model, MODEL_PRICING) == key


def test_gemma_4_rates_are_the_published_ones() -> None:
    assert MODEL_PRICING["google.gemma-4-31b"]["input"] == 0.14
    assert MODEL_PRICING["google.gemma-4-31b"]["output"] == 0.40
    assert MODEL_PRICING["google.gemma-4-26b-a4b"]["input"] == 0.13
