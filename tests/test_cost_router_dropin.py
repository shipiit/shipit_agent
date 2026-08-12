"""CostRouter as a drop-in `llm=` — routed, forwarded, accounted."""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.routing.cost_router import CostRouter, Tier


class TierLLM:
    model = "tier"

    def __init__(self, label):
        self.label = label
        self.calls = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.calls += 1
        return LLMResponse(content=f"answer from {self.label}", usage={"total_tokens": 5})


def _router(cheap, strong):
    return CostRouter(
        easy=Tier(llm=cheap, price_per_1k=0.001),
        medium=Tier(llm=cheap, price_per_1k=0.001),
        hard=Tier(llm=strong, price_per_1k=0.01),
    )


def test_router_is_a_working_llm_for_an_agent():
    cheap, strong = TierLLM("cheap"), TierLLM("strong")
    agent = Agent(
        llm=_router(cheap, strong),
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=2,
    )
    result = agent.run("hi")
    assert "answer from" in result.output
    assert cheap.calls + strong.calls >= 1


def test_router_filters_kwargs_the_delegate_cannot_accept():
    cheap, strong = TierLLM("cheap"), TierLLM("strong")
    router = _router(cheap, strong)
    # text_delta_callback is not accepted by TierLLM.complete — the router
    # must drop it instead of exploding.
    response = router.complete(
        messages=[], text_delta_callback=lambda c: None, tools=[], system_prompt=""
    )
    assert "answer from" in response.content
    assert router.report.tier_counts
