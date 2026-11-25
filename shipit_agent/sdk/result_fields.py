"""The parts of a ``ResultMessage`` worked out from a run's summary."""

from __future__ import annotations

from typing import Any

__all__ = ["model_usage", "terminal_reason"]

_REASONS = {
    "max_iterations": "max_turns",
    "max_budget_usd": "max_budget_usd",
    "budget_cost_unavailable": "max_budget_usd",
    "task_token_budget": "max_budget_tokens",
    "session_token_budget": "max_budget_tokens",
    "task_budget_usage_unavailable": "max_budget_tokens",
    "session_budget_usage_unavailable": "max_budget_tokens",
}


def terminal_reason(summary: dict[str, Any]) -> str:
    """Why the loop stopped: ``completed``, the limit it hit, or the run's own reason."""
    reason = summary.get("incomplete_reason")
    if reason:
        return _REASONS.get(str(reason), str(reason))
    return "completed" if summary.get("completion_status", "finished") == "finished" else "incomplete"


def model_usage(summary: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """Tokens and estimated cost for each model that served the run, in the SDK's key names."""
    buckets = (summary.get("usage_diagnostics") or {}).get("tokens_by_model") or {}
    if not buckets:
        return None
    from shipit_agent.costs.tracker import CostTracker

    tracker = CostTracker()
    usage: dict[str, dict[str, Any]] = {}
    for model, bucket in buckets.items():
        try:
            cost = tracker.calculate_cost(
                model,
                bucket.get("input", 0),
                bucket.get("output", 0),
                cache_read_tokens=bucket.get("cache_read", 0),
                cache_write_tokens=bucket.get("cache_write", 0),
                cache_write_1h_tokens=bucket.get("cache_write_1h", 0),
            )
        except (KeyError, TypeError, ValueError):
            # A malformed pricing entry must not fail the result.
            cost = 0.0
        usage[str(model)] = {
            "inputTokens": int(bucket.get("input", 0)),
            "outputTokens": int(bucket.get("output", 0)),
            "cacheReadInputTokens": int(bucket.get("cache_read", 0)),
            "cacheCreationInputTokens": int(bucket.get("cache_write", 0)),
            "costUSD": round(cost, 6),
        }
    return usage
