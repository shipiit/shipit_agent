"""The middle phase of a turn: call the model, step by step, until it answers.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.models import Message
from shipit_agent.core.state import RuntimeState
from shipit_agent.llms.base import (
    LLMResponse,
)


class TurnStepsMixin:
    """The middle phase of a turn: call the model, step by step, until it answers."""

    async def _run_steps(self, turn: Turn) -> None:
        """Call the model and run its tools, step by step, until it answers.

        Stops at a final answer, a cancellation, the task budget or the
        iteration limit, and leaves the last response on ``turn.response``.
        """
        user_prompt = turn.user_prompt
        state = turn.state
        registry = turn.registry
        tool_schemas = turn.tool_schemas
        base_prompt = turn.base_prompt
        shared_state = turn.shared_state

        response = LLMResponse(content="")
        if not await self._resume_deferred_call(turn):
            turn.response = self._paused(LLMResponse(content=""))
            return
        for iteration in range(1, self.max_iterations + 1):
            if self.task_budget_reached(state, iteration):
                response = LLMResponse(content=self.budget_stop_message())
                break
            if self._cancel_event.is_set():
                self.emit(
                    state,
                    "run_cancelled",
                    "Run cancelled by caller",
                    iteration=iteration,
                )
                if not response.content:
                    response = LLMResponse(content="[cancelled]")
                break
            self.watch_background_tasks(state, registry.values())
            # Deferred loading grows the advertised set mid-run, so the
            # selection is re-evaluated every step (a no-op when off).
            force_text = bool(
                shared_state.pop("force_text_after_duplicate", False)
                or shared_state.pop("force_text_after_malformed", False)
            )
            forced_names = set(shared_state.get("forced_tool_names") or ())
            force_any_tool = bool(shared_state.get("force_any_tool"))
            active_schemas = (
                []
                if force_text
                else self.without_withheld(
                    self.select_step_schemas(tool_schemas, shared_state), shared_state
                )
            )
            if forced_names:
                active_schemas = [
                    schema
                    for schema in active_schemas
                    if str((schema.get("function") or {}).get("name", ""))
                    in forced_names
                ]
            schemas_for_budget = (
                []
                if iteration == self.max_iterations and self.max_iterations > 1
                else active_schemas
            )
            self.account_request_overhead(schemas_for_budget)
            if self.hooks:
                self.hooks.run_before_llm(list(state.messages), active_schemas)

            # Compact when the window demands it (no-op unless
            # context_window_tokens is set), then re-ground.
            compacted_messages = self.compact(
                state, list(state.messages), iteration, shared_state
            )
            regrounding = self.regrounding_messages(shared_state)
            if regrounding:
                state.messages.extend(regrounding)
                compacted_messages = [*compacted_messages, *regrounding]

            compacted_messages = self.label_user_turns(compacted_messages)

            step_messages, step_schemas = self.step_request(
                messages=compacted_messages,
                tool_schemas=active_schemas,
                iteration=iteration,
                ran_tools=bool(state.tool_results) or state.tool_calls_attempted > 0,
            )
            if forced_names or force_any_tool:
                step_messages.append(
                    Message(
                        role="user",
                        content=(
                            (
                                "Execute the required registered tool now: "
                                + ", ".join(sorted(forced_names))
                                if forced_names
                                else "Execute the most appropriate available tool now"
                            )
                            + ". Emit the structured call, not prose or a simulated result."
                        ),
                        metadata={"internal": True, "kind": "required_tool"},
                    )
                )
            step_messages = self.fit_provider_request(
                state, step_messages, iteration=iteration
            )

            self.emit(
                state,
                "step_started",
                "LLM completion started",
                tool_count=len(step_schemas),
                iteration=iteration,
            )
            response = await self._complete_with_retry(
                state=state,
                messages=step_messages,
                tools=step_schemas,
                base_prompt=base_prompt,
                require_tool_call=bool(
                    (forced_names or force_any_tool) and step_schemas
                ),
            )
            self.track_usage(state, response, iteration)
            # Learn this model's real tokens-per-char from the view we just
            # sent, so the compaction trigger is calibrated, not guessed.
            self.calibrate_from_completion(step_messages, response)

            # Small models often emit the tool call as text; promote it.
            self.heal(state, response, registry, iteration)

            if self.hooks:
                self.hooks.run_after_llm(response)

            if force_text and response.tool_calls:
                self.ignore_calls_on_text_step(state, response, iteration)

            if response.reasoning_content:
                self.emit(
                    state,
                    "reasoning_started",
                    "Model reasoning started",
                    iteration=iteration,
                )
                self.emit(
                    state,
                    "reasoning_completed",
                    "Model reasoning completed",
                    iteration=iteration,
                    content=response.reasoning_content,
                )
            self._emit_assistant_message(state, response, iteration)

            if response.tool_calls:
                decision_summary = await self._generate_decision_summary(
                    state=state,
                    response=response,
                    user_prompt=user_prompt,
                    iteration=iteration,
                )
                if decision_summary:
                    self.emit(
                        state,
                        "agent_decision",
                        decision_summary,
                        summary=decision_summary,
                        next_action="call_tools",
                        tools=[
                            {
                                "name": call.name,
                                "arguments": dict(call.arguments),
                            }
                            for call in response.tool_calls
                        ],
                        iteration=iteration,
                        generated_by_model=bool(response.content),
                        summary_source=(
                            "model_text" if response.content else "tool_call"
                        ),
                    )

            if not response.tool_calls:
                if await self._settle_answer_step(
                    turn,
                    iteration=iteration,
                    response=response,
                    forced_names=forced_names,
                    force_any_tool=force_any_tool,
                    step_schemas=step_schemas,
                ):
                    break
                continue

            await self._run_tool_step(
                turn, iteration=iteration, response=response, forced_names=forced_names
            )
            if self._deferred_tool_use is not None:
                response = self._paused(response)
                break

        turn.response = response

    def _paused(self, response: LLMResponse) -> LLMResponse:
        """The response a run paused for a deferred call ends with."""
        self._last_finish_reason = "tool_deferred"
        return LLMResponse(content=self._pause_message(), usage=dict(response.usage or {}))

    def _emit_assistant_message(
        self, state: RuntimeState, response: LLMResponse, iteration: int
    ) -> None:
        """One event per model response: its text, thinking and tool calls.

        Text is left out when guardrails may rewrite the answer, so nothing
        reaches a client before redaction; the final answer arrives through
        ``final_answer`` once checked.
        """
        guarded = self.guardrails is not None and self.guardrails.modifies_output()
        self.emit(
            state,
            "assistant_message",
            "Model response",
            iteration=iteration,
            content="" if guarded else (response.content or ""),
            reasoning=response.reasoning_content or "",
            tool_calls=[
                {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
                for call in response.tool_calls
            ],
            model=str(getattr(self.llm, "model", "") or ""),
            usage=dict(response.usage or {}),
            stop_reason=response.metadata.get("finish_reason"),
        )
