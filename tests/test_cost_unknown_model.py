"""Regression tests for MEM-1: unknown-model pricing must not silently
under-count cost while a budget is active.

See FINDINGS.md MEM-1.
"""

from __future__ import annotations

import pytest

from shipit_agent.costs.budget import Budget
from shipit_agent.costs.tracker import CostTracker


class TestUnknownModelMetadata:
    def test_unknown_model_flags_record_metadata(self) -> None:
        """An unknown model marks the CostRecord and the tracker."""
        t = CostTracker()
        rec = t.record_call(
            model="totally-unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.cost_usd == 0.0
        assert rec.metadata.get("pricing") == "unknown"
        assert t.has_unknown_pricing is True

    def test_known_model_has_no_unknown_flag(self) -> None:
        """Known models leave the unknown-pricing flag clear."""
        t = CostTracker()
        rec = t.record_call(
            model="claude-sonnet-4",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.metadata.get("pricing") != "unknown"
        assert t.has_unknown_pricing is False

    def test_unknown_flag_in_to_dict(self) -> None:
        t = CostTracker()
        rec = t.record_call(model="nope", input_tokens=10, output_tokens=10)
        assert rec.to_dict()["metadata"].get("pricing") == "unknown"


class TestUnknownModelBackwardCompat:
    def test_unknown_model_no_budget_still_zero(self) -> None:
        """Without a budget the old contract holds: cost 0.0, no raise."""
        t = CostTracker()
        rec = t.record_call(
            model="unknown-model-xyz",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.cost_usd == 0.0
        assert t.total_cost == 0.0


class TestUnknownModelWithBudget:
    def test_unknown_model_with_budget_warns_but_does_not_crash(self) -> None:
        """Default 'warn': an unknown model under a budget surfaces via the
        flag (so the budget bypass is visible) but does NOT crash a legitimate
        run on a new/custom model id. Only on_unknown_model='error' raises."""
        t = CostTracker(budget=Budget(max_dollars=5.0))
        rec = t.record_call(
            model="bedrock-opus-unknown",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.cost_usd == 0.0
        assert rec.metadata.get("pricing") == "unknown"
        assert t.has_unknown_pricing is True

    def test_known_model_with_budget_unaffected(self) -> None:
        """Known models under a budget still record normally."""
        t = CostTracker(budget=Budget(max_dollars=1000.0))
        rec = t.record_call(
            model="claude-sonnet-4",
            input_tokens=1000,
            output_tokens=500,
        )
        assert rec.cost_usd > 0.0
        assert t.has_unknown_pricing is False

    def test_policy_error_always_raises(self) -> None:
        """on_unknown_model='error' raises even without a budget."""
        t = CostTracker(on_unknown_model="error")
        with pytest.raises(ValueError):
            t.record_call(model="nope", input_tokens=10, output_tokens=10)

    def test_policy_ignore_is_silent(self) -> None:
        """on_unknown_model='ignore' restores fully silent old behaviour."""
        t = CostTracker(budget=Budget(max_dollars=5.0), on_unknown_model="ignore")
        rec = t.record_call(model="nope", input_tokens=10, output_tokens=10)
        assert rec.cost_usd == 0.0
        assert t.has_unknown_pricing is False
