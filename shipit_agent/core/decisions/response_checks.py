"""Checking a model response: repair malformed tool calls, nudge or force text, and apply stop hooks.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from collections import Counter

from typing import Any, Sequence

from shipit_agent.core.models import Message
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.action_detection import is_malformed_action_attempt


class ResponseChecksMixin:
    """Checking a model response: repair malformed tool calls, nudge or force text, and apply stop hooks."""

    def heal(
        self, state: Any, response: LLMResponse, registry: Any, iteration: int
    ) -> None:
        """Promote tool calls a small model emitted as text, in place.

        The answer is searched first. If it yields nothing and the model
        produced *reasoning* but no answer and no calls, the reasoning is
        searched too: that shape means the model almost certainly wrote its
        call into its thinking, where nothing would otherwise find it.
        Reasoning heals the call only — the thinking text is left intact,
        since it was never going to be shown as the answer.
        """
        if not self.heal_tool_calls:
            return
        from shipit_agent.safety.tool_healing import (
            heal_tool_calls,
            merge_split_calls,
            schemas_from_tools,
        )

        tools = list(registry.values())
        names = {tool.name for tool in tools}
        schemas = schemas_from_tools(tools)

        # A model can split one call across several native single-argument
        # invocations too, not only in prose. Reassemble those before they run;
        # the merge is a no-op unless the same tool was called with disjoint
        # keys. Text healing below is only for turns with NO structured call.
        if response.tool_calls:
            merged = merge_split_calls(list(response.tool_calls), schemas)
            if len(merged) != len(response.tool_calls):
                self.emit(
                    state,
                    "tool_call_healed",
                    f"Merged {len(response.tool_calls)} split call(s) into "
                    f"{len(merged)}",
                    tools=[c.name for c in merged],
                    iteration=iteration,
                    healed_from="split_merge",
                )
                response.tool_calls = merged
            return

        healed: list[Any] = []
        source = "content"
        if response.content:
            cleaned, healed = heal_tool_calls(response.content, names, schemas=schemas)
            if healed:
                response.content = cleaned
        if not healed and response.reasoning_content:
            _, healed = heal_tool_calls(
                response.reasoning_content, names, schemas=schemas
            )
            source = "reasoning"

        if healed:
            response.tool_calls = healed
            self.emit(
                state,
                "tool_call_healed",
                f"Promoted {len(healed)} text tool call(s)",
                tools=[c.name for c in healed],
                iteration=iteration,
                healed_from=source,
            )

    def should_nudge(
        self,
        response: LLMResponse,
        *,
        has_tools: bool,
        last: bool,
        tool_names: Sequence[str] = (),
    ) -> bool:
        """Is this an unparsed call shape, and may we re-prompt once?"""
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        if self._nudges_used >= 1:
            return False
        raw_content = response.content or ""
        content = raw_content.strip()
        stalled = is_malformed_action_attempt(raw_content, allowed_names=tool_names)
        return stalled and content != self._last_nudged_text

    def record_nudge(self, response: LLMResponse) -> None:
        self._nudges_used += 1
        self._last_nudged_text = (response.content or "").strip()

    def should_force_text_recovery(
        self,
        response: LLMResponse,
        *,
        has_tools: bool,
        last: bool,
        tool_names: Sequence[str] = (),
    ) -> bool:
        """Stop advertising tools after a second malformed action attempt.

        Offered once a turn. The step after it has no tools, so whatever the
        model says there is its answer; switching again would loop forever
        on a model that keeps writing calls as prose.
        """
        if not (self.heal_tool_calls and has_tools and not last):
            return False
        if self._nudges_used < 1 or self._text_recovery_used:
            return False
        if not is_malformed_action_attempt(
            response.content or "", allowed_names=tool_names
        ):
            return False
        self._text_recovery_used = True
        return True

    @staticmethod
    def malformed_attempt_context(response: LLMResponse) -> str:
        """Keep a failed text-form action useful without replaying its loop."""
        from shipit_agent.safety.action_detection import is_degenerate_repetition

        content = response.content or ""
        if len(content) <= 2_048 and not is_degenerate_repetition(content):
            return content
        return (
            "[Malformed narrated tool attempt omitted: no structured tool call "
            "was emitted and the repeated prose was not executed.]"
        )

    def stable_final_content(self, state: Any, content: str) -> str:
        """Never expose a provider's degenerate repetition as a final answer."""
        from shipit_agent.safety.action_detection import is_degenerate_repetition

        if not is_degenerate_repetition(content):
            return content
        self.metadata["incomplete_reason"] = "degenerate_repetition"
        observation = str(getattr(state, "last_observation", "") or "").strip()
        detail = f" Completed tool work: {observation}" if observation else ""
        self.emit(
            state,
            "model_output_recovered",
            "Stopped a repetitive model response",
            reason="degenerate_repetition",
        )
        return (
            "I stopped the response because the model became stuck repeating "
            "an attempted action; that repeated text was not executed."
            f"{detail} No additional result is verified. Please retry this request."
        )

    def missing_answer_content(self, state: Any, *, reached_step_limit: bool) -> str:
        """The answer to give when the model left none: why, what ran, how to go on.

        Records the reason in ``incomplete_reason`` (unless a budget already
        did), so callers can tell a cut-short run from a finished one.
        """
        reason = "max_iterations" if reached_step_limit else "empty_response"
        if not self.metadata.get("incomplete_reason"):
            self.metadata["incomplete_reason"] = reason
        self.emit(
            state,
            "model_output_recovered",
            "Run ended without a final answer",
            reason=reason,
        )
        counts = Counter(result.name for result in state.tool_results)
        work = (
            "Tools run: "
            + ", ".join(
                f"{name} ({count} calls)" if count > 1 else name
                for name, count in counts.items()
            )
            + "."
            if counts
            else "No tools ran."
        )
        if reached_step_limit:
            return (
                f"I reached the step limit ({self.max_iterations} steps) before "
                f"writing a final answer. {work} Ask me to continue, or raise "
                "max_iterations for longer tasks."
            )
        return f"The model returned no final answer. {work} Please retry the request."

    def apply_stop_hooks(
        self, state: Any, response: LLMResponse, iteration: int, shared_state: dict
    ) -> bool:
        """Ask the stop hooks whether the run may finish. True means keep going:
        the reason has been added to the conversation and an event emitted."""
        hooks = getattr(self, "hooks", None)
        if hooks is None or not getattr(hooks, "stop", None):
            return False
        if iteration >= self.max_iterations:
            return False
        used = int(shared_state.get("stop_continuations", 0) or 0)
        if used >= self.MAX_STOP_CONTINUATIONS:
            if not shared_state.get("stop_cap_reported"):
                shared_state["stop_cap_reported"] = True
                self.emit(
                    state,
                    "stop_unresolved",
                    "Stop hooks still objected; finishing after the continuation limit",
                    iteration=iteration,
                    continuations=used,
                )
            return False
        try:
            reason = hooks.run_stop(response.content or "")
        except Exception as exc:  # a broken hook must not break the run
            self.emit(
                state,
                "stop_hook_error",
                f"Stop hook failed: {type(exc).__name__}",
                iteration=iteration,
            )
            return False
        if not reason:
            return False
        shared_state["stop_continuations"] = used + 1
        if response.content:
            state.messages.append(Message(role="assistant", content=response.content))
        state.messages.append(
            Message(
                role="user",
                content=(
                    f"Not done yet: {reason}\nKeep working until this is resolved, "
                    "then give your answer."
                ),
                metadata={"internal": True, "kind": "stop_hook"},
            )
        )
        self.emit(
            state,
            "stop_blocked",
            f"Kept going: {reason}",
            reason=reason,
            iteration=iteration,
            continuation=used + 1,
        )
        return True
