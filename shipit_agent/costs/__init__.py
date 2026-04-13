"""Cost Tracking & Budget Enforcement for LLM agent runs.

Provides real-time USD cost calculation based on per-model token pricing,
configurable budgets with warning thresholds, and hook integration for
automatic tracking.

Example::

    from shipit_agent.costs import CostTracker, Budget

    tracker = CostTracker(budget=Budget(max_dollars=5.00))
    agent = Agent.with_builtins(llm=llm, hooks=tracker.as_hooks())
    result = agent.run("Analyze this codebase")
    print(tracker.total_cost)    # 1.23
    print(tracker.summary())     # full cost breakdown
"""

from __future__ import annotations

from .budget import Budget, BudgetExceededError
from .pricing import MODEL_ALIASES, MODEL_PRICING
from .tracker import CostRecord, CostTracker

__all__ = [
    "Budget",
    "BudgetExceededError",
    "CostRecord",
    "CostTracker",
    "MODEL_ALIASES",
    "MODEL_PRICING",
]
