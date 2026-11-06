"""The last phase of a turn: settle the final answer, save the session and report the result.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.models import Message
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.llms.base import (
    LLMResponse,
)
from shipit_agent.stores import (
    MemoryFact,
    SessionRecord,
)


class TurnFinishMixin:
    """The last phase of a turn: settle the final answer, save the session and report the result."""

    async def _finish_turn(self, turn: Turn) -> tuple[RuntimeState, LLMResponse]:
        """Close a turn: settle the final answer, save the session, report the result."""
        state = turn.state
        base_prompt = turn.base_prompt
        existing_session = turn.existing_session
        fact_ledger = turn.fact_ledger
        original_prior = turn.original_prior
        response = turn.response
        appended_response_id = turn.appended_response_id

        # Calls still pending at the last step never ran, so the step limit
        # stopped the run even when the response also carried text (that
        # text is a preamble, not an answer): summarise instead.
        hit_iteration_cap = bool(response.tool_calls)
        reached_step_limit = hit_iteration_cap
        if hit_iteration_cap and self.task_budget_reached(
            state, self.max_iterations + 1
        ):
            response = LLMResponse(content=self.budget_stop_message())
            hit_iteration_cap = False
        if hit_iteration_cap:
            self.emit(
                state,
                "step_started",
                "Final summarization turn (iteration cap reached)",
                tool_count=0,
                iteration=self.max_iterations + 1,
            )
            try:
                summary = await self._complete_with_retry(
                    state=state,
                    messages=list(state.messages),
                    tools=[],
                    base_prompt=base_prompt,
                )
                # Account for the summary turn's tokens + fire the hook.
                self.track_usage(state, summary, self.max_iterations + 1)
                if self.hooks:
                    self.hooks.run_after_llm(summary)
                # A summary that only repeats the pending text adds nothing.
                if summary.content and summary.content != response.content:
                    response = summary
            except Exception:
                pass

        if reached_step_limit and not self.metadata.get("incomplete_reason"):
            # A summary may rescue the answer, but the task still stopped short.
            self.metadata["incomplete_reason"] = "max_iterations"
        response.content = self.stable_final_content(state, response.content)
        if not (response.content or "").strip() and not self._cancel_event.is_set():
            steps_taken = max(
                (
                    event.payload.get("iteration", 0)
                    for event in state.events
                    if event.type == "step_started"
                    and event.payload.get("iteration", 0) <= self.max_iterations
                ),
                default=0,
            )
            # The last step withholds tools to force an answer; an empty
            # reply there is still the step limit, not a silent model.
            response.content = self.missing_answer_content(
                state,
                reached_step_limit=reached_step_limit
                or steps_taken >= self.max_iterations,
            )

        # Skip if this exact response was already appended in the loop.
        if response.content and id(response) != appended_response_id:
            state.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    metadata={
                        **dict(response.metadata),
                        **(
                            {"reasoning_content": response.reasoning_content}
                            if response.reasoning_content
                            else {}
                        ),
                    },
                )
            )

        for tool_result in state.tool_results:
            if not tool_result.metadata.get("persist", False):
                continue
            self.memory_store.add(
                MemoryFact(
                    content=f"{tool_result.name}: {tool_result.output}",
                    category="tool_result",
                    metadata=dict(tool_result.metadata),
                )
            )

        # Reassemble with the ORIGINAL prior turns (see eviction note above):
        # [fresh system] + [unevicted prior] + [everything this run added].
        persisted_messages = [
            state.messages[0],
            *original_prior,
            *(
                message
                for message in state.messages[1 + len(original_prior) :]
                if message.metadata.get("kind") != "verified_session_facts"
            ),
        ]
        session_metadata = dict(existing_session.metadata) if existing_session else {}
        session_metadata["token_calibration"] = self.token_calibrator.to_dict()
        session_metadata["tool_discovery"] = self.discovery_checkpoint()
        fact_ledger.ingest_tool_results(state.tool_results)
        if len(fact_ledger):
            session_metadata["verified_facts"] = fact_ledger.to_list()
        latest_checkpoint = (
            self.compactor().latest() if self.context_window_tokens >= 0 else None
        )
        if latest_checkpoint is not None:
            session_metadata["compaction_checkpoint"] = latest_checkpoint.to_dict()
        # A deferred call waits in the session until the next run settles it.
        if self._deferred_tool_use is not None:
            session_metadata["deferred_tool_use"] = dict(self._deferred_tool_use)
        else:
            session_metadata.pop("deferred_tool_use", None)
        self.session_store.save(
            SessionRecord(
                session_id=self.session_id,
                messages=persisted_messages,
                metadata=session_metadata,
            )
        )
        self.surface_give_up(state.tool_results)
        response.content = self.sanitize_output(state, response.content)
        self.emit(
            state,
            "final_answer",
            "Final answer generated",
            content=response.content,
            format="markdown",
        )

        # Closing accounting: iterations, tool calls, compactions and usage.
        summary = self._build_run_summary(state)
        self.emit(state, "run_summary", summary["headline"], **summary)
        self.emit(
            state,
            "run_completed",
            "Agent run completed",
            output=response.content,
            content=response.content,
            format="markdown",
            usage=dict(self._total_usage),
            summary=summary,
            cancelled=self._cancel_event.is_set(),
        )

        # MCP transports are closed by run()'s finally (covers the error path).
        return state, response
