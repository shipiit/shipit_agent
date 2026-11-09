"""The budget checks a CostTracker runs after each recorded call."""

from __future__ import annotations

import logging
from typing import Callable

from .budget import Budget, BudgetExceededError
from .records import CostRecord

# The tracker's logger, so warnings keep the name callers filter on.
logger = logging.getLogger("shipit_agent.costs.tracker")


class BudgetChecksMixin:
    """Warn once at the budget's threshold; raise once it is exceeded."""

    _budget: Budget | None
    _calls: list[CostRecord]
    _total_cost: float
    _warning_emitted: bool
    _on_cost_alert: Callable[[float, float], None] | None

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

    def _check_warning(self) -> None:
        """Emit a cost warning if the threshold has been crossed."""
        if (
            self._budget
            and not self._warning_emitted
            and self._budget.should_warn(self._total_cost)
        ):
            self._warning_emitted = True
            logger.warning(
                "Cost alert: $%.4f spent of $%.4f budget (%.0f%%)",
                self._total_cost,
                self._budget.max_dollars,
                (self._total_cost / self._budget.max_dollars) * 100,
            )
            if self._on_cost_alert:
                self._on_cost_alert(self._total_cost, self._budget.max_dollars)
