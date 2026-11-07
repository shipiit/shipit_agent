"""The cost budget: estimate a run's spend and stop when ``max_budget_usd`` is reached.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any


class CostBudgetMixin:
    """The cost budget: estimate a run's spend and stop when ``max_budget_usd`` is reached."""

    def run_cost_usd(self) -> float | None:
        """The run's estimated spend so far, from public model pricing.

        A best-effort estimate, never a billing figure: ``0`` for a model not
        in the pricing table, ``None`` when pricing fails outright.
        """
        usage = self._total_usage
        cost_usd: float | None = None
        model = getattr(self.llm, "model", None)
        if len(self._usage_by_model) > 1:
            # Several models served this run: price each at its own rate.
            try:
                from shipit_agent.costs.tracker import CostTracker

                tracker = CostTracker()
                cost_usd = round(
                    sum(
                        tracker.calculate_cost(
                            name,
                            b["input"],
                            b["output"],
                            cache_read_tokens=b["cache_read"],
                            cache_write_tokens=b["cache_write"],
                        )
                        for name, b in self._usage_by_model.items()
                    ),
                    6,
                )
            except (KeyError, TypeError, ValueError):
                # A malformed pricing entry must not fail the run summary.
                cost_usd = None
        elif model:
            try:
                from shipit_agent.costs.tracker import CostTracker

                cost_usd = round(
                    CostTracker().calculate_cost(
                        str(model),
                        self._total_uncached_input,
                        usage.get("completion_tokens", 0),
                        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                        cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
                    ),
                    6,
                )
            except Exception:
                cost_usd = None
        return cost_usd

    def _cost_budget_hit(self, state: Any, iteration: int) -> bool:
        limit = self.metadata.get("max_budget_usd")
        if limit is None or not self._completed_model_calls:
            return False
        from shipit_agent.costs.tracker import CostTracker

        tracker = CostTracker()
        models = list(self._usage_by_model) or [getattr(self.llm, "model", None)]
        if not all(model and tracker.has_pricing(str(model)) for model in models):
            # Spend that cannot be measured cannot be capped; stopping is the
            # only way to honour a budget the caller asked for.
            self.metadata["incomplete_reason"] = "budget_cost_unavailable"
            self.emit(
                state,
                "budget_unavailable",
                "No pricing data for this model; stopping the cost-capped run",
                limit=limit,
                iteration=iteration,
                scope="cost",
            )
            return True
        spent = self.run_cost_usd()
        if spent is None or spent < limit:
            return False
        self.metadata["incomplete_reason"] = "max_budget_usd"
        self.emit(
            state,
            "budget_exhausted",
            "Cost budget reached",
            limit=limit,
            used=round(spent, 6),
            iteration=iteration,
            enforcement="between_steps",
            scope="cost",
        )
        return True
