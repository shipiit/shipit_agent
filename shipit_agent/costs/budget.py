"""Budget definitions and enforcement errors for cost tracking."""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceededError(Exception):
    """Raised when an agent exceeds its cost budget.

    Attributes:
        spent:  Total USD spent so far.
        budget: Configured budget limit in USD.
        model:  Model ID of the call that caused the breach.
    """

    def __init__(self, spent: float, budget: float, model: str) -> None:
        self.spent = spent
        self.budget = budget
        self.model = model
        super().__init__(
            f"Budget exceeded: ${spent:.4f} spent of "
            f"${budget:.4f} limit (model: {model})"
        )


@dataclass(slots=True)
class Budget:
    """Cost budget for an agent run.

    Attributes:
        max_dollars: Maximum spend allowed in USD.
        warn_at:     Fraction (0.0 -- 1.0) at which to emit a
                     ``cost_alert`` notification.  Default ``0.80`` (80%).
    """

    max_dollars: float
    warn_at: float = 0.80

    def should_warn(self, spent: float) -> bool:
        """Return ``True`` when *spent* crosses the warning threshold."""
        return spent >= self.max_dollars * self.warn_at

    def is_exceeded(self, spent: float) -> bool:
        """Return ``True`` when *spent* exceeds the budget limit."""
        return spent > self.max_dollars
