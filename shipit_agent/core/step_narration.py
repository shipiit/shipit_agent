"""Narrating progress: one plain line saying what the agent is about to do, and what a step found.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from shipit_agent.core.models import Message, ToolResult
from shipit_agent.core.narration import (
    _arguments_by_name,
    _bounded,
    _describe_result,
    _first_sentences,
    _join_clauses,
    _looks_like_prose,
    _result_failed,
)
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.llms.base import (
    LLMResponse,
)
from shipit_agent.narrate.verbs import summarize


class StepNarrationMixin:
    """Narrating progress: one plain line saying what the agent is about to do, and what a step found."""

    async def _generate_decision_summary(
        self,
        *,
        state: RuntimeState,
        response: LLMResponse,
        user_prompt: str,
        iteration: int,
    ) -> str:
        """Create the same bounded progress line as the synchronous runtime."""
        if not self.progress_summaries:
            return ""
        spoken = _first_sentences(response.content)
        if _looks_like_prose(spoken):
            return spoken
        calls = list(response.tool_calls or [])
        if not calls:
            return ""

        if self.decision_llm is not None:
            actions = "\n".join(
                f"- {call.name}({_bounded(dict(call.arguments or {}), 250)})"
                for call in calls
            )
            prompt = (
                "Write one short first-person progress line for the user.\n"
                f"They asked: {_bounded(user_prompt, 250)}\n"
                f"Last step: {_bounded(state.last_observation, 250) or 'none'}\n"
                f"About to run:\n{actions}\n"
                "Use only these facts; do not claim a result yet."
            )
            try:
                narrator = self.decision_llm
                async_complete = getattr(narrator, "acomplete", None)
                kwargs = {
                    "messages": [Message(role="user", content=prompt)],
                    "tools": [],
                    "system_prompt": (
                        "Narrate agent progress in plain language, without markdown "
                        "or private reasoning. Use two short sentences at most."
                    ),
                    "metadata": {
                        **dict(self.metadata),
                        "purpose": "agent_decision_summary",
                        "iteration": iteration,
                    },
                }
                if callable(async_complete):
                    narrated = async_complete(**kwargs)
                    result = (
                        await narrated if inspect.isawaitable(narrated) else narrated
                    )
                else:
                    result = await asyncio.to_thread(narrator.complete, **kwargs)
                if getattr(result, "usage", None):
                    self.track_usage(state, result, iteration)
                text = _first_sentences(getattr(result, "content", ""))
                if _looks_like_prose(text):
                    return text
            except Exception as exc:  # noqa: BLE001
                self.emit(
                    state,
                    "progress_summary_failed",
                    "Progress summary generation failed",
                    purpose="agent_decision_summary",
                    iteration=iteration,
                    error=str(exc),
                )

        actions = [
            summarize(call.name, dict(call.arguments or {})).present_label()
            for call in calls
        ]
        return _join_clauses(actions) + "."

    def _generate_observation_summary(
        self,
        *,
        tool_results: list[ToolResult],
        tool_calls: list[Any],
    ) -> str:
        """Describe bounded tool outcomes without another model call."""
        if not tool_results or not self.progress_summaries:
            return ""
        arguments = _arguments_by_name(tool_calls)
        clauses: list[str] = []
        for result in tool_results:
            label = summarize(result.name, arguments.get(result.name, {})).past_label()
            if _result_failed(result):
                clauses.append(f"{label} — failed")
            else:
                detail = _describe_result(result)
                clauses.append(f"{label} — {detail}" if detail else label)
        return _join_clauses(clauses) + "."
