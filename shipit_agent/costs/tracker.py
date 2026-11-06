"""Real-time cost tracker with per-model pricing and budget enforcement.

:class:`CostTracker` records every LLM call, computes its USD cost from
the pricing table, enforces budgets, and integrates with
:class:`AgentHooks` for automatic tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from shipit_agent.safety.hooks import AgentHooks

from .budget import Budget
from .budget_checks import BudgetChecksMixin
from .pricing import MODEL_PRICING
from .pricing_lookup import PricingLookupMixin
from .records import CostRecord
# Re-exported: callers and tests import these from here.
from .records import _extract_model as _extract_model
from .records import _extract_usage as _extract_usage
from .tracker_hooks import tracker_hooks

logger = logging.getLogger(__name__)


class CostTracker(BudgetChecksMixin, PricingLookupMixin):
    """Real-time cost tracking with per-model pricing and budget enforcement.

    Integrates with :class:`AgentHooks` to automatically track cost
    across LLM calls, emit ``cost_alert`` events at budget thresholds,
    and raise :class:`BudgetExceededError` when limits are exceeded.

    Example::

        tracker = CostTracker(budget=Budget(max_dollars=5.00))
        agent = Agent.with_builtins(llm=llm, hooks=tracker.as_hooks())
        result = agent.run("Analyze codebase")
        print(tracker.total_cost)       # 1.23
        print(tracker.breakdown())      # per-call cost attribution

    Args:
        budget:        Optional :class:`Budget` for enforcement.
        pricing:       Optional dict to override / extend
                       :data:`MODEL_PRICING`.
        on_cost_alert: Optional callback invoked when the budget
                       warning threshold is crossed.  Receives
                       ``(spent, budget_limit)`` as arguments.
        on_unknown_model: Policy for a model that has no pricing entry.

                       * ``"warn"`` (default): record the call with
                         ``cost_usd == 0.0``, flag the
                         :class:`CostRecord` with
                         ``metadata={"pricing": "unknown"}``, set
                         :attr:`has_unknown_pricing`, and log a warning.
                         If a :class:`Budget` is attached this also
                         raises :class:`BudgetExceededError` so the
                         budget is never silently under-counted.
                       * ``"error"``: always raise ``ValueError`` for an
                         unknown model, regardless of budget.
                       * ``"ignore"``: legacy behaviour — silently treat
                         the cost as ``$0.00`` (no flag, no raise).
    """

    def __init__(
        self,
        budget: Budget | None = None,
        pricing: dict[str, dict[str, float]] | None = None,
        on_cost_alert: Callable[[float, float], None] | None = None,
        on_unknown_model: Literal["warn", "error", "ignore"] = "warn",
    ) -> None:
        self._calls: list[CostRecord] = []
        self._total_cost: float = 0.0
        self._pricing: dict[str, dict[str, float]] = {
            **MODEL_PRICING,
            **(pricing or {}),
        }
        self._budget = budget
        self._on_cost_alert = on_cost_alert
        self._on_unknown_model = on_unknown_model
        self._warning_emitted: bool = False
        self._has_unknown_pricing: bool = False

    @property
    def has_unknown_pricing(self) -> bool:
        """``True`` if any recorded call used a model with no pricing entry.

        When this is ``True`` the reported :attr:`total_cost` is a *lower
        bound*: at least one call was billed at ``$0.00`` because its model
        is absent from the pricing table.
        """
        return self._has_unknown_pricing

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_cost(self) -> float:
        """Total accumulated cost in USD."""
        return self._total_cost

    @property
    def total_tokens(self) -> dict[str, int]:
        """Aggregate token counts across all recorded calls."""
        totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        for rec in self._calls:
            totals["input_tokens"] += rec.input_tokens
            totals["output_tokens"] += rec.output_tokens
            totals["cache_read_tokens"] += rec.cache_read_tokens
            totals["cache_write_tokens"] += rec.cache_write_tokens
        return totals

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> CostRecord:
        """Record an LLM call and return its cost breakdown.

        Also checks the budget and emits warnings or raises
        :class:`BudgetExceededError` as appropriate.
        """
        is_unknown = self._resolve_model(model) not in self._pricing

        if is_unknown and self._on_unknown_model == "error":
            raise ValueError(
                f"No pricing data for model '{model}' and "
                f"on_unknown_model='error'."
            )

        cost = self.calculate_cost(
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        metadata: dict[str, Any] = {}
        flag_unknown = is_unknown and self._on_unknown_model != "ignore"
        if flag_unknown:
            metadata["pricing"] = "unknown"
            self._has_unknown_pricing = True

        record = CostRecord(
            call_number=len(self._calls) + 1,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )
        self._calls.append(record)
        self._total_cost += cost

        logger.debug(
            "Call #%d (%s): %d in / %d out = $%.6f  (total: $%.4f)",
            record.call_number,
            model,
            input_tokens,
            output_tokens,
            cost,
            self._total_cost,
        )

        # An unknown-priced call under an active budget is billed at $0.00 and
        # cannot trip the budget. Surface it loudly via a warning + the
        # ``has_unknown_pricing`` flag (set above) rather than crashing a
        # legitimate run on a model that's simply new/custom. Callers who want
        # a hard failure opt in with ``on_unknown_model="error"`` (handled at
        # the top of this method, before any cost is computed).
        if flag_unknown and self._budget is not None and not self._warning_emitted:
            logger.warning(
                "Model '%s' has no pricing data: it is billed at $0.00, so the "
                "$%.2f budget cannot be enforced for these calls. Check "
                "tracker.has_unknown_pricing or pass on_unknown_model='error' "
                "to fail hard.",
                model,
                self._budget.max_dollars,
            )

        # Budget checks (on the known-priced portion of the spend).
        self._check_warning()
        self.check_budget()

        return record

    def breakdown(self) -> list[dict[str, Any]]:
        """Return per-call cost attribution as a list of dicts."""
        return [rec.to_dict() for rec in self._calls]

    def summary(self) -> dict[str, Any]:
        """Return cost summary with total, breakdown, and budget status."""
        tokens = self.total_tokens
        result: dict[str, Any] = {
            "total_cost_usd": round(self._total_cost, 6),
            "total_calls": len(self._calls),
            "total_tokens": tokens,
            "calls": self.breakdown(),
        }

        if self._budget:
            result["budget"] = {
                "max_dollars": self._budget.max_dollars,
                "warn_at": self._budget.warn_at,
                "remaining": round(self._budget.max_dollars - self._total_cost, 6),
                "percent_used": round(
                    (self._total_cost / self._budget.max_dollars) * 100, 2
                )
                if self._budget.max_dollars > 0
                else 0.0,
            }

        return result

    def reset(self) -> None:
        """Reset all tracked costs and call history."""
        self._calls.clear()
        self._total_cost = 0.0
        self._warning_emitted = False

    # ------------------------------------------------------------------
    # Hook integration
    # ------------------------------------------------------------------

    def as_hooks(self, model_name: str | None = None) -> AgentHooks:
        """Create :class:`AgentHooks` that auto-track cost and enforce budget.

        The ``on_after_llm`` hook extracts token usage from the LLM
        response and records it.  The ``on_before_llm`` hook checks
        the budget before each call.

        Args:
            model_name: Explicit model name override.  If ``None`` the
                tracker will attempt to read the model from the
                response object.
        """
        return tracker_hooks(self, model_name)
