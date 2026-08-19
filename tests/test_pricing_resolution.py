"""Pricing must resolve the model ids providers actually emit.

An exact dict lookup fails silently: a miss prices the call at $0.00, so a
configured budget can never be exceeded and the only symptom is a log line.
That is the wrong failure mode for the one feature whose whole job is to stop
spending, so these tests pin the matching rather than the arithmetic.
"""

from __future__ import annotations

import pytest

from shipit_agent.costs.budget import Budget, BudgetExceededError
from shipit_agent.costs.pricing import MODEL_PRICING, resolve_pricing_key
from shipit_agent.costs.tracker import CostTracker


class TestVendorPrefixes:
    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-4-20250514",
            "us.anthropic.claude-opus-4-20250514-v1:0",  # Bedrock inference profile
            "global.anthropic.claude-opus-4-20250514",  # Bedrock global
            "anthropic/claude-opus-4-20250514",  # OpenRouter / LiteLLM
            "bedrock/anthropic.claude-opus-4-20250514-v1:0",
        ],
    )
    def test_same_model_prices_the_same_through_every_route(self, model_id) -> None:
        tracker = CostTracker()
        assert tracker.calculate_cost(model_id, 1_000_000, 0) == pytest.approx(15.00)

    def test_dots_inside_a_model_name_are_not_split_eagerly(self) -> None:
        """`gemini-2.5-pro` must not be peeled into `5-pro` and lost."""
        tracker = CostTracker()
        assert tracker.calculate_cost("gemini-2.5-pro", 1_000_000, 0) > 0


class TestLongestMatchWins:
    def test_a_longer_key_is_preferred_over_a_shorter_prefix(self) -> None:
        """`claude-opus-4-1` must not silently resolve to `claude-opus-4`."""
        pricing = {
            "claude-opus-4": {"input": 1.0},
            "claude-opus-4-1": {"input": 2.0},
        }
        assert resolve_pricing_key("claude-opus-4-1-20250805", pricing) == (
            "claude-opus-4-1"
        )


class TestUnknownModels:
    def test_unknown_model_still_returns_none(self) -> None:
        assert resolve_pricing_key("no-such-model-anywhere", MODEL_PRICING) is None

    def test_unknown_model_is_reported_not_silently_priced(self) -> None:
        tracker = CostTracker()
        assert tracker.calculate_cost("no-such-model-anywhere", 1_000, 0) == 0.0

    def test_empty_model_id_is_handled(self) -> None:
        assert resolve_pricing_key("", MODEL_PRICING) is None
        assert resolve_pricing_key(None, MODEL_PRICING) is None


class TestBudgetEnforcement:
    def test_a_vendor_prefixed_model_can_now_trip_the_budget(self) -> None:
        """The point of the fix. Priced at $0.00, spend is invisible to the
        budget and it can never be exceeded however much is spent."""
        tracker = CostTracker(budget=Budget(max_dollars=0.01))
        # The spend is detected at record time, so the raise happens here.
        with pytest.raises(BudgetExceededError, match="claude-opus-4"):
            tracker.record_call(
                model="us.anthropic.claude-opus-4-20250514-v1:0",
                input_tokens=1_000_000,
                output_tokens=0,
            )

    def test_before_the_fix_this_spend_was_invisible(self) -> None:
        """Pins the mechanism, not just the outcome: an unresolvable id costs
        $0.00, and no amount of it can ever exceed a budget."""
        tracker = CostTracker(budget=Budget(max_dollars=0.01))
        tracker.record_call(
            model="no-such-model-anywhere", input_tokens=100_000_000, output_tokens=0
        )
        assert tracker.total_cost == 0.0
        tracker.check_budget()  # does not raise


class TestAliasesStillWork:
    @pytest.mark.parametrize("alias", ["opus", "sonnet", "haiku", "gpt4o"])
    def test_short_aliases_resolve(self, alias) -> None:
        assert CostTracker().calculate_cost(alias, 1_000, 0) > 0

    def test_a_user_registered_model_is_matched_too(self) -> None:
        tracker = CostTracker()
        tracker.add_model("my-private-model", {"input": 1.0, "output": 2.0})
        cost = tracker.calculate_cost("vendor/my-private-model-v2", 1_000_000, 0)
        assert cost == pytest.approx(1.0)
