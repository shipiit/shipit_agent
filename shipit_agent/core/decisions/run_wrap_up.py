"""Wrapping up a run: the run summary, surfacing tools that gave up, and closing MCP connections.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.result_subtype import result_subtype


class RunWrapUpMixin:
    """Wrapping up a run: the run summary, surfacing tools that gave up, and closing MCP connections."""

    def _build_run_summary(self, state: Any) -> dict[str, Any]:
        """A closing accounting of the run — iterations, tools, tokens, cost.

        Everything here was already tracked; this consolidates it into one
        artifact a UI can print as the run's final line. Cost is a best-effort
        estimate from the model's public pricing (``0`` / unknown when the
        model isn't in the table), never a billing figure.
        """
        usage = dict(self._total_usage)
        tool_results = list(getattr(state, "tool_results", []) or [])
        events = list(getattr(state, "events", []) or [])
        tool_calls = sum(1 for e in events if e.type == "tool_called")
        compactions = sum(1 for e in events if e.type == "context_compacted")
        iterations = max(
            (e.payload.get("iteration", 0) for e in events if e.type == "step_started"),
            default=0,
        )
        cost_usd = self.run_cost_usd()
        total = usage.get("total_tokens", 0)
        cache_read = max(0, int(usage.get("cache_read_input_tokens", 0) or 0))
        cache_creation = max(0, int(usage.get("cache_creation_input_tokens", 0) or 0))
        cache_eligible_input = self._total_context_input
        cache_hit_ratio = (
            round(cache_read / cache_eligible_input, 4) if cache_eligible_input else 0.0
        )
        cost_str = f", ${cost_usd:.4f}" if cost_usd else ""
        summary: dict[str, Any] = {
            "headline": (
                f"Run finished: {iterations} iterations, {tool_calls} tool "
                f"calls, {total:,} tokens{cost_str}"
            ),
            "iterations": iterations,
            "tool_calls": tool_calls,
            "tool_results": len(tool_results),
            "compactions": compactions,
            "usage": usage,
            "usage_diagnostics": {
                "estimated_main_request_content_tokens": dict(self._request_estimates),
                "reported_tokens_by_purpose": dict(self._purpose_usage),
                "prefix_changes": self._prefix_changes,
                "cache_counters_reported": self._cache_counters_reported,
                "task_token_limit": self.metadata.get("max_task_tokens"),
                "session_token_limit": self.metadata.get("max_session_tokens"),
                "session_tokens_used": self._session_runtime_state.get(
                    "session_tokens", 0
                ),
                "discarded_tokens": self._discarded_tokens,
                "tokens_by_model": {
                    name: dict(b) for name, b in self._usage_by_model.items()
                },
                "budget_enforcement": "between_steps",
                "provider_usage_available": bool(self._usage_reports),
                "budget_usage_complete": self._complete_usage_reports
                == self._completed_model_calls,
                "llm_retry_events": sum(e.type == "llm_retry" for e in events),
            },
            "cache": {
                "read_input_tokens": cache_read,
                "creation_input_tokens": cache_creation,
                "eligible_input_tokens": cache_eligible_input,
                "hit_ratio": cache_hit_ratio,
            },
            "estimated_cost_usd": cost_usd,
            "gave_up": bool(self.metadata.get("gave_up")),
            "completion_status": (
                "incomplete"
                if self.metadata.get("incomplete_reason")
                or self.metadata.get("gave_up")
                or getattr(self, "_last_finish_reason", None)
                in {"length", "max_tokens", "content_filter"}
                else "finished"
            ),
            "finish_reason": getattr(self, "_last_finish_reason", None),
            "tool_discovery": self.discovery_checkpoint(),
            "incomplete_reason": self.metadata.get("incomplete_reason"),
            "failed_tool_results": sum(bool(r.is_error) for r in tool_results),
            "recovery_events": sum(
                e.type in {"llm_retry", "tool_call_healed", "model_output_recovered"}
                for e in events
            ),
        }
        summary["subtype"] = result_subtype(summary)
        return summary

    def surface_give_up(self, tool_results: list[Any]) -> None:
        """Promote a declared stop from a tool result to run metadata."""
        gave_up = next((r for r in tool_results if r.metadata.get("gave_up")), None)
        if gave_up is not None:
            self.metadata["gave_up"] = True
            self.metadata["give_up_reason"] = gave_up.metadata.get("give_up_reason", "")
            self.metadata["give_up_needs"] = gave_up.metadata.get("give_up_needs", [])

    def close_mcps(self) -> None:
        """Close every attached MCP transport, swallowing close errors.

        Must run even when the loop raises, or a failed run leaks live
        subprocesses and sockets.
        """
        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
