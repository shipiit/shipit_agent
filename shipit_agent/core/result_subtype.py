"""How a run ended, as one of the Claude Agent SDK's result subtypes.

``success`` for a finished run; otherwise the limit that stopped it
(``error_max_turns``, ``error_max_budget_usd``, ``error_max_budget_tokens``)
or ``error_during_execution`` for everything else that left the task
unfinished. ``error_max_budget_tokens`` is shipit's own: the SDK has no
token budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

ResultSubtype = Literal[
    "success",
    "error_max_turns",
    "error_max_budget_usd",
    "error_max_budget_tokens",
    "error_during_execution",
]

_BY_REASON: dict[str, ResultSubtype] = {
    "max_iterations": "error_max_turns",
    "max_budget_usd": "error_max_budget_usd",
    "budget_cost_unavailable": "error_max_budget_usd",
    "task_token_budget": "error_max_budget_tokens",
    "session_token_budget": "error_max_budget_tokens",
    "task_budget_usage_unavailable": "error_max_budget_tokens",
    "session_budget_usage_unavailable": "error_max_budget_tokens",
}


def result_subtype(summary: Mapping[str, Any] | None) -> ResultSubtype:
    """The subtype for a run summary (``result.metadata["run_summary"]``)."""
    if not summary:
        return "success"
    reason = summary.get("incomplete_reason")
    if reason:
        return _BY_REASON.get(str(reason), "error_during_execution")
    if summary.get("completion_status", "finished") == "finished":
        return "success"
    return "error_during_execution"
