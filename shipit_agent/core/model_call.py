"""Calling the model: native async or a worker thread, retries with backoff, and progress narration.

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
    accepts_kwarg,
    accepts_text_delta_callback,
    accepts_tool_input_callback,
)
from shipit_agent.narrate.verbs import summarize


class ModelCallMixin:
    """Calling the model: native async or a worker thread, retries with backoff, and progress narration."""

    async def _complete_async(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        """Use a provider's native async API, with a context-preserving fallback."""
        from shipit_agent.safety.action_detection import RepetitionGuard

        loop = asyncio.get_running_loop()
        repetition_guard = RepetitionGuard()
        provisional_chars = 0
        # Keep final answers streaming when tool schemas remain advertised.
        # Native structured tool calling separates calls from answer text;
        # schema availability alone is not evidence that this is a tool step.
        #
        # Stream unless a guardrail could rewrite the answer after the fact:
        # output-modifying rules (secret/PII redaction, output blocklist,
        # custom/judge output check) must buffer the whole answer to redact
        # before display. Input and tool-output rules don't touch the answer
        # stream, so a set with only those streams live.
        expose_text_deltas = (
            self.guardrails is None or not self.guardrails.modifies_output()
        )

        def _schedule_emit(event_type: str, message: str, **payload: Any) -> None:
            loop.call_soon_threadsafe(
                lambda: self.emit(state, event_type, message, **payload)
            )

        def _on_text_delta(chunk: str) -> bool | None:
            nonlocal provisional_chars
            if not chunk:
                return None
            provisional_chars += len(chunk)
            if repetition_guard.add(chunk):
                return False
            if (
                require_tool_call
                and self.max_required_tool_text_chars
                and provisional_chars >= self.max_required_tool_text_chars
            ):
                return False
            if (
                self.max_completion_text_chars
                and provisional_chars >= self.max_completion_text_chars
            ):
                return False
            if expose_text_deltas:
                _schedule_emit("text_delta", "", chunk=chunk)
            return None

        parsers: dict[str, Any] = {}
        emitted: dict[str, int] = {}
        argument_guards: dict[str, RepetitionGuard] = {}
        argument_chars: dict[str, int] = {}

        def _on_tool_input(call_id: str, tool_name: str, fragment: str) -> bool | None:
            from shipit_agent.narrate.json_stream import (
                StreamingToolInputParser,
                streaming_field_for,
            )

            argument_chars[call_id] = argument_chars.get(call_id, 0) + len(fragment)
            guard = argument_guards.setdefault(call_id, RepetitionGuard())
            repeated = guard.add(fragment)
            if (repeated and argument_chars[call_id] >= 512) or (
                self.max_tool_argument_chars
                and argument_chars[call_id] >= self.max_tool_argument_chars
            ):
                return False

            parser = parsers.get(call_id)
            if parser is None:
                field = streaming_field_for(tool_name)
                if field is None:
                    parsers[call_id] = False
                    return None
                parser = parsers[call_id] = StreamingToolInputParser(field)
                emitted[call_id] = 0
                _schedule_emit(
                    "tool_input_started",
                    f"Writing {tool_name} input",
                    tool=tool_name,
                    call_id=call_id,
                    field=field,
                )
            if parser is False:
                return None
            parser.append(fragment)
            if parser.has_error:
                parsers[call_id] = False
                return None
            value = parser.streaming_value
            new = value[emitted[call_id] :]
            if new:
                emitted[call_id] = len(value)
                _schedule_emit(
                    "tool_input_delta",
                    "",
                    tool=tool_name,
                    call_id=call_id,
                    delta=new,
                )
            return None

        complete_kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            system_prompt=base_prompt,
            metadata=dict(self.metadata),
        )
        async_complete = getattr(self.llm, "acomplete", None)
        complete_fn = async_complete if callable(async_complete) else self.llm.complete
        from shipit_agent.llms.base import accepts_explicit_kwarg

        if require_tool_call and accepts_explicit_kwarg(
            complete_fn, "require_tool_call"
        ):
            complete_kwargs["require_tool_call"] = True
        # Per-request timeout, only for adapters that can honour it — same
        # decision as the sync loop.
        if self.retry_policy.request_timeout is not None and accepts_kwarg(
            complete_fn, "timeout"
        ):
            complete_kwargs["timeout"] = self.retry_policy.request_timeout
        if accepts_text_delta_callback(complete_fn):
            complete_kwargs["text_delta_callback"] = _on_text_delta
        if accepts_tool_input_callback(complete_fn):
            complete_kwargs["tool_input_callback"] = _on_tool_input
        if (
            self.response_format
            and not tools
            and accepts_kwarg(complete_fn, "response_format")
        ):
            complete_kwargs["response_format"] = self.response_format

        if callable(async_complete):
            result = async_complete(**complete_kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        # asyncio.to_thread propagates contextvars; run_in_executor does not.
        return await asyncio.to_thread(self.llm.complete, **complete_kwargs)

    async def _complete_with_retry(
        self,
        *,
        state: RuntimeState,
        messages: list[Message],
        tools: list[dict[str, Any]],
        base_prompt: str,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return await self._complete_async(
                    state=state,
                    messages=messages,
                    tools=tools,
                    base_prompt=base_prompt,
                    require_tool_call=require_tool_call,
                )
            except self.retry_policy.retry_on_exceptions as exc:
                if attempt >= self.retry_policy.max_llm_retries:
                    raise
                attempt += 1
                delay = self.retry_policy.llm_retry_delay(attempt)
                self.emit(
                    state,
                    "llm_retry",
                    "Retrying LLM completion",
                    attempt=attempt,
                    error=str(exc),
                    delay=round(delay, 3),
                )
                if delay > 0:
                    await asyncio.sleep(delay)

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
