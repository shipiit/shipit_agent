"""Usage and budgets: count tokens and cost per step, and stop when a session or task budget is spent.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any, Sequence

from shipit_agent.core.models import Message
from shipit_agent.llms.base import LLMResponse


class UsageBudgetMixin:
    """Usage and budgets: count tokens and cost per step, and stop when a session or task budget is spent."""

    def track_usage(self, state: Any, response: LLMResponse, iteration: int) -> None:
        """Accumulate tokens and emit a running total for the live footer."""
        self._last_finish_reason = response.metadata.get("finish_reason")
        from shipit_agent.llms.usage import has_complete_token_usage, input_token_counts

        uncached, read, write, total_input = input_token_counts(response)
        self._total_uncached_input += uncached
        route = (
            response.metadata.get("route")
            if isinstance(response.metadata, dict)
            else None
        )
        self._bucket(
            (route or {}).get("model") or getattr(self.llm, "model", None),
            uncached,
            response.usage.get("completion_tokens", 0),
            read,
            write,
        )
        self._total_context_input += total_input
        purpose = (
            "compaction"
            if response.metadata.get("purpose") == "context_compaction"
            else "main"
        )
        self._purpose_usage[purpose] += total_input + response.usage.get(
            "completion_tokens", 0
        )
        self._completed_model_calls += 1
        self._usage_reports += int(bool(response.usage))
        self._complete_usage_reports += int(has_complete_token_usage(response))
        self._cache_counters_reported |= any(
            key in response.usage
            for key in ("cache_read_input_tokens", "cache_creation_input_tokens")
        )
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            self._total_usage[key] += response.usage.get(key, 0)
        spent = total_input + response.usage.get("completion_tokens", 0)
        discarded = response.metadata.get("discarded_usage")
        if isinstance(discarded, dict):
            spent += self._count_discarded(discarded)
        session = self._session_runtime_state
        session["session_tokens"] = session.get("session_tokens", 0) + spent
        if not has_complete_token_usage(response):
            session["session_usage_complete"] = False
        self.emit(
            state,
            "usage_tick",
            "Usage updated",
            usage=dict(self._total_usage),
            iteration=iteration,
        )

    def _count_discarded(self, usage: dict[str, Any]) -> int:
        """Book a routed step's thrown-away call into totals and budgets.

        Deliberately not into calibration: that learns only from the call
        whose prompt it estimated, and this one was a different model.
        """
        from shipit_agent.llms.usage import input_token_counts

        counted = {
            key: int(value)
            for key, value in usage.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        uncached, read, write, total_input = input_token_counts(
            LLMResponse(usage=counted)
        )
        tokens = total_input + counted.get("completion_tokens", 0)
        self._total_uncached_input += uncached
        self._bucket(
            usage.get("model"),
            uncached,
            counted.get("completion_tokens", 0),
            read,
            write,
        )
        self._total_context_input += total_input
        self._purpose_usage["main"] += tokens
        self._discarded_tokens += tokens
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            self._total_usage[key] += counted.get(key, 0)
        return tokens

    def _bucket(
        self, model: Any, uncached: int, output: int, read: int, write: int
    ) -> None:
        if not model:
            return
        bucket = self._usage_by_model.setdefault(
            str(model), {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        )
        bucket["input"] += uncached
        bucket["output"] += output
        bucket["cache_read"] += read
        bucket["cache_write"] += write

    def budget_stop_message(self) -> str:
        scope = (
            "session"
            if str(self.metadata.get("incomplete_reason") or "").startswith("session")
            else "task"
        )
        policy = (
            "session token budget" if scope == "session" else "task token budget policy"
        )
        return (
            f"Stopped by the {policy}. Work is incomplete; "
            "completed tool results remain in the session."
        )

    def task_budget_reached(self, state: Any, iteration: int) -> bool:
        """Between steps: stop if the run's or the session's budget is spent."""
        return self._task_budget_hit(state, iteration) or self._session_budget_hit(
            state, iteration
        )

    def _session_budget_hit(self, state: Any, iteration: int) -> bool:
        limit = self.metadata.get("max_session_tokens")
        if limit is None:
            return False
        session = self._session_runtime_state
        if session.get("session_usage_complete", True) is False:
            self.metadata["incomplete_reason"] = "session_budget_usage_unavailable"
            self.emit(
                state,
                "budget_unavailable",
                "Provider did not report complete usage; stopping the budgeted session",
                limit=limit,
                iteration=iteration,
                scope="session",
            )
            return True
        used = session.get("session_tokens", 0)
        if used < limit:
            return False
        self.metadata["incomplete_reason"] = "session_token_budget"
        self.emit(
            state,
            "budget_exhausted",
            "Session token budget reached",
            limit=limit,
            used=used,
            iteration=iteration,
            enforcement="between_steps",
            scope="session",
        )
        return True

    def _task_budget_hit(self, state: Any, iteration: int) -> bool:
        limit = self.metadata.get("max_task_tokens")
        used = self._total_context_input + self._total_usage.get("completion_tokens", 0)
        if (
            limit is not None
            and self._complete_usage_reports < self._completed_model_calls
        ):
            self.metadata["incomplete_reason"] = "task_budget_usage_unavailable"
            self.emit(
                state,
                "budget_unavailable",
                "Provider did not report complete usage; stopping budgeted work",
                limit=limit,
                iteration=iteration,
            )
            return True
        if limit is None or used < limit:
            return False
        self.metadata["incomplete_reason"] = "task_token_budget"
        self.emit(
            state,
            "budget_exhausted",
            "Task token budget reached",
            limit=limit,
            used=used,
            iteration=iteration,
            enforcement="between_steps",
        )
        return True

    def calibrate_from_completion(
        self, sent_messages: Sequence[Message], response: LLMResponse
    ) -> None:
        """Teach the token calibrator from one MAIN completion.

        ``sent_messages`` is the exact view that was sent — the compacted
        messages, not the full history — so the estimate matches what the
        provider actually tokenised. The estimate uses the SAME formula the
        compaction trigger does (messages + fixed prefix) so the learned factor
        is applied to the number it was measured against. ``actual`` respects
        each adapter's cache-counter semantics: native Anthropic separates
        cached input, whereas OpenAI and LiteLLM include it in prompt tokens.
        Call ONLY for real model steps — never the summary completion,
        whose prompt is a different shape.
        """
        from shipit_agent.context.compaction import count_messages
        from shipit_agent.llms.usage import input_token_counts

        actual = input_token_counts(response)[3]
        if actual <= 0:
            return
        # A router answers for several models; learn for the one that ran.
        route = (
            response.metadata.get("route")
            if isinstance(response.metadata, dict)
            else None
        )
        model = (route or {}).get("model") or getattr(self.llm, "model", None)
        estimated = count_messages(sent_messages, model) + self._fixed_prefix_tokens
        self.token_calibrator.observe(model, estimated, actual)
