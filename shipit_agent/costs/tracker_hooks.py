"""AgentHooks that feed a CostTracker from every model call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shipit_agent.safety.hooks import AgentHooks

from .records import _extract_model, _extract_usage

if TYPE_CHECKING:
    from .tracker import CostTracker


def tracker_hooks(tracker: CostTracker, model_name: str | None = None) -> AgentHooks:
    """Check the budget before each model call and record the usage after it."""
    hooks = AgentHooks()

    # -- before LLM: pre-call budget check -------------------------
    def _before_llm(messages: list[Any], tools: list[Any]) -> None:
        # Raise early if we have already exceeded the budget.
        tracker.check_budget()

    hooks.on_before_llm(_before_llm)

    # -- after LLM: record usage -----------------------------------
    def _after_llm(response: Any) -> None:
        # Extract usage from the response.  The exact attribute path
        # depends on the LLM wrapper, so we try several patterns.
        usage = _extract_usage(response)
        model = model_name or _extract_model(response) or "unknown"

        if usage:
            input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
            if (getattr(response, "metadata", {}) or {}).get("prompt_tokens_include_cache"):
                input_tokens = max(0, input_tokens
                    - usage.get("cache_read_input_tokens", 0)
                    - usage.get("cache_creation_input_tokens", 0))
            tracker.record_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=usage.get("output_tokens", 0)
                or usage.get("completion_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0)
                or usage.get("cache_read_tokens", 0),
                cache_write_tokens=usage.get("cache_creation_input_tokens", 0)
                or usage.get("cache_write_tokens", 0),
            )

    hooks.on_after_llm(_after_llm)

    return hooks
