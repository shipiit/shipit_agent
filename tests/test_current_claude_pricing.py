"""Current Claude models are priced, at their own rates.

The table stopped at the Claude 4 generation: current models had no price
(so cost read $0 and a cost-capped run stopped at once), and prefix matching
priced Opus 4.8 as the old Opus 4, at three times its rate.
"""

from __future__ import annotations

import pytest

from shipit_agent.costs.tracker import CostTracker

#: model -> (input $/MTok, output $/MTok)
CURRENT = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}


@pytest.mark.parametrize(("model", "prices"), sorted(CURRENT.items()))
def test_each_current_model_has_its_own_price(
    model: str, prices: tuple[float, float]
) -> None:
    tracker = CostTracker()
    assert tracker.has_pricing(model)
    cost = tracker.calculate_cost(model, 1_000_000, 1_000_000)
    assert cost == pytest.approx(prices[0] + prices[1])


@pytest.mark.parametrize(
    "routed",
    [
        "us.anthropic.claude-opus-5-5",
        "anthropic/claude-sonnet-5-5",
        "bedrock/anthropic.claude-haiku-5-5",
    ],
)
def test_routed_ids_find_their_model(routed: str) -> None:
    assert CostTracker().has_pricing(routed)


def test_cache_reads_cost_less_than_input() -> None:
    tracker = CostTracker()
    for model in CURRENT:
        full = tracker.calculate_cost(model, 1_000_000, 0)
        cached = tracker.calculate_cost(model, 0, 0, cache_read_tokens=1_000_000)
        assert 0 < cached < full, model
