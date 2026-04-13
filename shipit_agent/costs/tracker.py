"""Real-time cost tracker with per-model pricing and budget enforcement.

:class:`CostTracker` records every LLM call, computes its USD cost from
the pricing table, enforces budgets, and integrates with
:class:`AgentHooks` for automatic tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from shipit_agent.hooks import AgentHooks

from .budget import Budget, BudgetExceededError
from .pricing import MODEL_ALIASES, MODEL_PRICING

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CostRecord:
    """Record of a single LLM call's cost.

    Attributes:
        call_number:        Monotonically increasing call index.
        model:              Model identifier used for pricing lookup.
        input_tokens:       Number of prompt tokens.
        output_tokens:      Number of completion tokens.
        cache_read_tokens:  Tokens read from prompt cache (Anthropic).
        cache_write_tokens: Tokens written to prompt cache (Anthropic).
        cost_usd:           Computed cost in US dollars.
        timestamp:          UTC time of the call.
    """

    call_number: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "call_number": self.call_number,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp": self.timestamp.isoformat(),
        }


class CostTracker:
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
    """

    def __init__(
        self,
        budget: Budget | None = None,
        pricing: dict[str, dict[str, float]] | None = None,
        on_cost_alert: Callable[[float, float], None] | None = None,
    ) -> None:
        self._calls: list[CostRecord] = []
        self._total_cost: float = 0.0
        self._pricing: dict[str, dict[str, float]] = {
            **MODEL_PRICING,
            **(pricing or {}),
        }
        self._budget = budget
        self._on_cost_alert = on_cost_alert
        self._warning_emitted: bool = False

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
        cost = self.calculate_cost(
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        record = CostRecord(
            call_number=len(self._calls) + 1,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost,
            timestamp=datetime.utcnow(),
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

        # Budget checks.
        self._check_warning()
        self.check_budget()

        return record

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for a given token count.

        If the model is not found in the pricing table the cost is
        returned as ``0.0`` and a warning is logged.
        """
        resolved = self._resolve_model(model)
        prices = self._pricing.get(resolved)

        if prices is None:
            logger.warning(
                "No pricing data for model '%s' — cost will be $0.00", model
            )
            return 0.0

        per_million = 1_000_000.0
        cost = (
            input_tokens * prices.get("input", 0.0) / per_million
            + output_tokens * prices.get("output", 0.0) / per_million
            + cache_read_tokens * prices.get("cache_read", 0.0) / per_million
            + cache_write_tokens * prices.get("cache_write", 0.0) / per_million
        )
        return cost

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
                "remaining": round(
                    self._budget.max_dollars - self._total_cost, 6
                ),
                "percent_used": round(
                    (self._total_cost / self._budget.max_dollars) * 100, 2
                )
                if self._budget.max_dollars > 0
                else 0.0,
            }

        return result

    def add_model(self, model_id: str, pricing: dict[str, float]) -> None:
        """Register pricing for a custom or new model.

        Args:
            model_id: The model identifier string.
            pricing:  Dict with keys like ``"input"``, ``"output"``,
                      ``"cache_read"``, ``"cache_write"`` mapping to
                      per-million-token prices in USD.
        """
        self._pricing[model_id] = pricing

    def check_budget(self) -> None:
        """Check if budget is exceeded.

        Raises:
            BudgetExceededError: If the accumulated cost exceeds the
                budget limit.
        """
        if self._budget and self._budget.is_exceeded(self._total_cost):
            # Use the most recent model if available.
            model = self._calls[-1].model if self._calls else "unknown"
            raise BudgetExceededError(
                spent=self._total_cost,
                budget=self._budget.max_dollars,
                model=model,
            )

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
        hooks = AgentHooks()

        # -- before LLM: pre-call budget check -------------------------
        def _before_llm(messages: list[Any], tools: list[Any]) -> None:
            # Raise early if we have already exceeded the budget.
            self.check_budget()

        hooks.on_before_llm(_before_llm)

        # -- after LLM: record usage -----------------------------------
        def _after_llm(response: Any) -> None:
            # Extract usage from the response.  The exact attribute path
            # depends on the LLM wrapper, so we try several patterns.
            usage = _extract_usage(response)
            model = model_name or _extract_model(response) or "unknown"

            if usage:
                self.record_call(
                    model=model,
                    input_tokens=usage.get("input_tokens", 0)
                    or usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0)
                    or usage.get("completion_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0)
                    or usage.get("cache_read_tokens", 0),
                    cache_write_tokens=usage.get(
                        "cache_creation_input_tokens", 0
                    )
                    or usage.get("cache_write_tokens", 0),
                )

        hooks.on_after_llm(_after_llm)

        return hooks

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_model(self, model: str) -> str:
        """Resolve a model alias to its canonical pricing key."""
        return MODEL_ALIASES.get(model, model)

    def _check_warning(self) -> None:
        """Emit a cost warning if the threshold has been crossed."""
        if (
            self._budget
            and not self._warning_emitted
            and self._budget.should_warn(self._total_cost)
        ):
            self._warning_emitted = True
            logger.warning(
                "Cost alert: $%.4f spent of $%.2f budget (%.0f%%)",
                self._total_cost,
                self._budget.max_dollars,
                (self._total_cost / self._budget.max_dollars) * 100,
            )
            if self._on_cost_alert:
                self._on_cost_alert(
                    self._total_cost, self._budget.max_dollars
                )


# ---------------------------------------------------------------------------
# Helper functions for extracting usage from diverse LLM responses
# ---------------------------------------------------------------------------


def _extract_usage(response: Any) -> dict[str, int] | None:
    """Best-effort extraction of token usage from an LLM response object."""
    # Pattern 1: response.usage as a dict-like object.
    if hasattr(response, "usage"):
        usage = response.usage
        if isinstance(usage, dict):
            return usage
        # Anthropic / OpenAI SDK objects expose attributes.
        if hasattr(usage, "input_tokens"):
            result: dict[str, int] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
            # Anthropic cache fields.
            for key in (
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                val = getattr(usage, key, 0)
                if val:
                    result[key] = val
            return result
        if hasattr(usage, "prompt_tokens"):
            return {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
            }

    # Pattern 2: response.metadata["usage"].
    if hasattr(response, "metadata") and isinstance(response.metadata, dict):
        usage = response.metadata.get("usage")
        if isinstance(usage, dict):
            return usage

    # Pattern 3: shipit_agent LLMResponse with raw_response.
    if hasattr(response, "raw_response"):
        return _extract_usage(response.raw_response)

    return None


def _extract_model(response: Any) -> str | None:
    """Best-effort extraction of the model name from an LLM response."""
    if hasattr(response, "model"):
        return str(response.model)
    if hasattr(response, "metadata") and isinstance(response.metadata, dict):
        return response.metadata.get("model")
    if hasattr(response, "raw_response") and hasattr(
        response.raw_response, "model"
    ):
        return str(response.raw_response.model)
    return None
