"""A step where the model answered without calling a tool: required-tool nudges, the verify gate and stop hooks.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.models import Message
from shipit_agent.llms.base import (
    LLMResponse,
)


class AnswerStepMixin:
    """A step where the model answered without calling a tool: required-tool nudges, the verify gate and stop hooks."""

    async def _settle_answer_step(
        self,
        turn: Turn,
        *,
        iteration: int,
        response: LLMResponse,
        forced_names: set[str],
        force_any_tool: bool,
        step_schemas: list[dict[str, Any]],
    ) -> bool:
        """Handle a step where the model answered without calling a tool.

        Nudges the model when a required tool never ran, enforces the verify
        gate and stop hooks, and returns ``True`` when the turn is done or
        ``False`` to run another step.
        """
        state = turn.state
        registry = turn.registry
        shared_state = turn.shared_state
        tool_schemas = turn.tool_schemas
        user_prompt = turn.user_prompt

        force_any_retries = int(shared_state.get("force_any_retries", 0) or 0)
        if (
            force_any_tool
            # Unsatisfiable with no tool advertised this step: retrying
            # would only loop the required-tool nudge.
            and step_schemas
            and iteration < self.max_iterations
            and force_any_retries < self.MAX_FORCE_ANY_RETRIES
        ):
            shared_state["force_any_retries"] = force_any_retries + 1
            state.messages.append(
                Message(
                    role="assistant",
                    content="[Unverified response discarded: no required tool executed.]",
                )
            )
            state.messages.append(
                Message(
                    role="user",
                    content=(
                        "A registered tool must execute before answering. "
                        "Call the best available tool now; do not simulate its result."
                    ),
                    metadata={"internal": True, "kind": "required_tool_retry"},
                )
            )
            self.emit(
                state,
                "tool_call_healed",
                "Retrying required tool use",
                nudge=True,
                iteration=iteration,
            )
            return False
        # Give up forcing after the cap rather than re-emitting the same
        # retry to max_iterations (the "Retrying required tool use" loop).
        if force_any_tool:
            shared_state.pop("force_any_tool", None)
            force_any_tool = False
            self.emit(
                state,
                "step",
                "Required tool did not execute; answering from available context",
                iteration=iteration,
            )
        executed = {result.name for result in state.tool_results}
        missing_required = sorted(forced_names - executed - self._requested_tool_nudges)
        missing_requested = self.missing_requested_tools(
            user_prompt, registry, state.tool_results
        )
        missing_requested = sorted(set(missing_requested) | set(missing_required))
        if missing_requested and iteration < self.max_iterations:
            self.record_requested_tool_nudge(missing_requested)
            shared_state["forced_tool_names"] = set(missing_requested)
            state.messages.append(
                Message(
                    role="assistant",
                    content="[Unverified response discarded: no requested tool executed.]",
                )
            )
            state.messages.append(
                Message(
                    role="user",
                    content=(
                        "The requested registered tool did not execute. Call "
                        + ", ".join(missing_requested)
                        + " now; do not simulate or invent its result."
                    ),
                    metadata={"internal": True, "kind": "requested_tool_retry"},
                )
            )
            self.emit(
                state,
                "tool_call_healed",
                "Retrying an explicitly requested tool",
                tools=missing_requested,
                nudge=True,
                iteration=iteration,
            )
            return False
        # Nudge-on-stall: the model narrated an action and called
        # nothing. One tightly-gated re-prompt recovers the turn.
        if self.should_nudge(
            response,
            has_tools=bool(tool_schemas),
            last=iteration >= self.max_iterations,
            tool_names=tuple(tool.name for tool in registry.values()),
        ):
            self.record_nudge(response)
            state.messages.append(
                Message(
                    role="assistant",
                    content=self.malformed_attempt_context(response),
                )
            )
            state.messages.append(
                Message(
                    role="user",
                    content=self.NUDGE_TEXT,
                    metadata={"internal": True, "kind": "tool_call_retry"},
                )
            )
            self.emit(
                state,
                "tool_call_healed",
                "Nudged: malformed tool call",
                nudge=True,
                iteration=iteration,
            )
            return False
        if self.should_force_text_recovery(
            response,
            has_tools=bool(tool_schemas),
            last=iteration >= self.max_iterations,
            tool_names=tuple(tool.name for tool in registry.values()),
        ):
            shared_state["force_text_after_malformed"] = True
            state.messages.append(
                Message(
                    role="assistant",
                    content=self.malformed_attempt_context(response),
                )
            )
            state.messages.append(
                Message(
                    role="user",
                    content=(
                        "The structured action failed twice. Do not call or "
                        "describe any tool now. Answer the original request "
                        "concisely from completed results already above, and "
                        "state what could not be verified."
                    ),
                    metadata={
                        "internal": True,
                        "kind": "text_only_recovery",
                    },
                )
            )
            self.emit(
                state,
                "tool_call_healed",
                "Switching to text-only recovery after repeated malformed calls",
                recovery="text_only",
                iteration=iteration,
            )
            return False
        if state.verify_gate is not None:
            if iteration < self.max_iterations:
                verify_nudge = state.verify_gate.stop_nudge()
                if verify_nudge:
                    if response.content:
                        state.messages.append(
                            Message(role="assistant", content=response.content)
                        )
                        turn.appended_response_id = id(response)
                    state.messages.append(
                        Message(
                            role="user",
                            content=verify_nudge,
                            metadata={
                                "internal": True,
                                "kind": "verify_retry",
                            },
                        )
                    )
                    self.emit(
                        state,
                        "verify_required",
                        "Edited code without passing verification — running tests",
                        iteration=iteration,
                    )
                    return False
            elif state.verify_gate.would_nudge():
                self.emit(
                    state,
                    "verify_skipped",
                    "Edited code but ran out of steps before verification passed",
                    iteration=iteration,
                )
        if self.apply_stop_hooks(state, response, iteration, shared_state):
            if response.content:
                turn.appended_response_id = id(response)
            return False
        return True
