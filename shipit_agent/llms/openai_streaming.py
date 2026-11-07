"""Streaming an OpenAI Chat Completions call: text and tool-argument deltas, usage, early stop.

Mixed into :class:`~shipit_agent.llms.openai_adapter.OpenAIChatLLM`.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.litellm_adapter import (
    _extract_reasoning,
    _iter_with_deadline,
    _parse_tool_arguments,
)
from shipit_agent.llms.openai_common import (
    _BUFFERED_DELTA_CHARS,
    _buffered_deltas,
    _usage_dict,
)


class OpenAIStreamingMixin:
    """Streaming an OpenAI Chat Completions call."""

    def _complete_streaming(
        self,
        client: Any,
        kwargs: dict[str, Any],
        on_delta: Any,
        on_tool_input: Any = None,
        timeout: Any = None,
    ) -> LLMResponse:
        """Token-by-token completion — same LLMResponse shape as non-streaming.

        Text deltas hit ``on_delta`` the moment they arrive; tool-call
        fragments are stitched together by index. ``stream_options`` is
        retried without ``include_usage`` for OpenAI-compatible providers
        that reject it (e.g. some gateways).
        """
        try:
            stream = client.chat.completions.create(
                **kwargs, stream=True, stream_options={"include_usage": True}
            )
        except Exception as first_exc:
            exc_name = type(first_exc).__name__
            status = getattr(first_exc, "status_code", None)
            if (
                status in (429, 500, 502, 503, 529)
                or "RateLimitError" in exc_name
                or "ServiceUnavailable" in exc_name
                or "InternalServerError" in exc_name
            ):
                raise ConnectionError(f"{exc_name}: {first_exc}") from first_exc
            try:  # provider may not support stream_options
                stream = client.chat.completions.create(**kwargs, stream=True)
            except Exception:
                raise first_exc from None

        # Some gateways (and test fakes) ignore stream=True and return a plain
        # completion object. Detect that and degrade gracefully. The upstream
        # response was buffered, so this cannot restore time-to-first-token;
        # bounded synthetic deltas only preserve the consumer/UI contract.
        if hasattr(stream, "choices"):
            choice = stream.choices[0].message
            content = choice.content or ""
            deltas = _buffered_deltas(content)
            emitted_deltas = 0
            stopped = False
            if on_delta is not None:
                for delta in deltas:
                    emitted_deltas += 1
                    try:
                        should_continue = on_delta(delta)
                    except Exception:
                        # Match native-stream behavior: observers may fail,
                        # but only an explicit False controls generation.
                        should_continue = None
                    if should_continue is False:
                        # The gateway already generated the full response, so
                        # we cannot refund those provider tokens. We can still
                        # enforce the runtime contract: stop publishing and do
                        # not return the rejected suffix as the final answer.
                        content = content[: emitted_deltas * _BUFFERED_DELTA_CHARS]
                        stopped = True
                        break
            usage: dict[str, int] = {}
            if getattr(stream, "usage", None):
                usage = _usage_dict(stream.usage)
            tool_calls = []
            for call in choice.tool_calls or []:
                arguments = call.function.arguments or "{}"
                tool_calls.append(
                    ToolCall(
                        name=call.function.name,
                        arguments=_parse_tool_arguments(arguments),
                        id=str(getattr(call, "id", "") or ""),
                    )
                )
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                metadata={
                    "model": self.model,
                    "provider": "openai",
                    "streamed": False,
                    "buffered_fallback": True,
                    "finish_reason": getattr(stream.choices[0], "finish_reason", None),
                    "prompt_tokens_include_cache": True,
                    "synthetic_deltas": emitted_deltas,
                    **({"stream_stopped": "callback"} if stopped else {}),
                },
                reasoning_content=_extract_reasoning(choice),
                usage=usage,
            )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}  # index → {id, name, arguments}
        usage: dict[str, int] = {}
        stopped_reason: str | None = None
        finish_reason: str | None = None

        for chunk in _iter_with_deadline(stream, timeout):
            if getattr(chunk, "usage", None):
                usage = _usage_dict(chunk.usage)
            if not getattr(chunk, "choices", None):
                continue
            finish_reason = (
                getattr(chunk.choices[0], "finish_reason", None) or finish_reason
            )
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)
                # Streaming mode is entered when EITHER callback is set;
                # a tool-input-only caller has no text callback to invoke.
                if on_delta is not None:
                    try:
                        if on_delta(text) is False:
                            stopped_reason = "degenerate_repetition"
                            close = getattr(stream, "close", None)
                            if callable(close):
                                close()
                            break
                    except Exception:
                        # A UI subscriber cannot be allowed to kill the model
                        # stream; the runtime's own stop signal is ``False``.
                        pass
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(str(reasoning))
            for frag in getattr(delta, "tool_calls", None) or []:
                idx = getattr(frag, "index", 0) or 0
                slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if getattr(frag, "id", None):
                    slot["id"] = frag.id
                fn = getattr(frag, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        # Assign, don't concatenate: a provider that repeats
                        # the name on every fragment would otherwise build
                        # "get_weatherget_weather". Names arrive whole; only
                        # ARGUMENTS stream in fragments.
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["arguments"] += fn.arguments
                        if on_tool_input is not None and slot["name"]:
                            # The provider streams argument JSON in fragments
                            # exactly as Anthropic does; forward them so a
                            # renderer can show the file being written. The
                            # index stands in for a call id — OpenAI does not
                            # send one until the call completes.
                            try:
                                callback_result = on_tool_input(
                                    slot["id"] or f"call_{idx}",
                                    slot["name"],
                                    fn.arguments,
                                )
                                if callback_result is False:
                                    stopped_reason = "tool_argument_guard"
                                    close = getattr(stream, "close", None)
                                    if callable(close):
                                        close()
                                    break
                            except Exception:
                                pass
            if stopped_reason:
                break

        tool_calls = []
        for idx in sorted(calls):
            raw = calls[idx]["arguments"] or "{}"
            arguments = _parse_tool_arguments(raw)
            tool_calls.append(
                ToolCall(
                    name=calls[idx]["name"],
                    arguments=arguments,
                    id=calls[idx]["id"],
                    index=idx,
                ).ensure_id()
            )

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "openai",
                "streamed": True,
                "finish_reason": finish_reason,
                "prompt_tokens_include_cache": True,
                **({"stream_stopped": stopped_reason} if stopped_reason else {}),
            },
            reasoning_content="".join(reasoning_parts) or None,
            usage=usage,
        )
