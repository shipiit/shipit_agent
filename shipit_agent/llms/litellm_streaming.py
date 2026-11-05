"""Streaming a LiteLLM completion, and reading cache usage and reasoning off a response."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.litellm_messages import (
    _parse_tool_arguments,
)
from shipit_agent.llms.litellm_usage import _extract_cache_usage


def _iter_with_deadline(stream: Any, timeout: Any):
    """Yield a blocking provider stream under one absolute deadline.

    SDK/socket timeouts commonly apply to each individual read. A provider
    that emits one small chunk before every deadline can therefore occupy an
    agent forever. The producer thread isolates that blocking iterator while
    this consumer enforces the caller's total per-request budget.
    """
    try:
        seconds = float(timeout)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        yield from stream
        return

    items: queue.Queue[tuple[str, Any]] = queue.Queue()

    def consume() -> None:
        try:
            for item in stream:
                items.put(("item", item))
        except BaseException as exc:  # forwarded on the calling thread
            items.put(("error", exc))
        finally:
            items.put(("done", None))

    threading.Thread(target=consume, name="shipit-llm-stream", daemon=True).start()
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"LLM stream exceeded {seconds:g} seconds")
        try:
            kind, value = items.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(f"LLM stream exceeded {seconds:g} seconds") from exc
        if kind == "item":
            yield value
        elif kind == "error":
            raise value
        else:
            return


def _stream_completion(
    *,
    completion_fn: Any,
    model: str,
    payload_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    extra_kwargs: dict[str, Any],
    text_delta_callback: Callable[[str], bool | None] | None,
    tool_input_callback: Callable[[str, str, str], bool | None] | None = None,
) -> LLMResponse:
    """Drive a streaming litellm completion, accumulating text and tool calls.

    Invokes ``text_delta_callback`` for every textual chunk as it arrives so
    upstream code can stream tokens to the client in real time. Returns the
    same ``LLMResponse`` a non-streaming call would, so the rest of the
    runtime is unchanged.
    """
    try:
        stream = completion_fn(
            model=model,
            messages=payload_messages,
            tools=tools,
            stream=True,
            stream_options={"include_usage": True},
            **extra_kwargs,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if (
            status in (429, 500, 502, 503, 529)
            or "ServiceUnavailable" in exc_name
            or "RateLimitError" in exc_name
            or "InternalServerError" in exc_name
        ):
            raise ConnectionError(f"{exc_name}: {exc}") from exc
        raise

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    # index -> partial {"id": str, "name": str, "arguments": str}
    tool_call_acc: dict[int, dict[str, str]] = {}
    usage: dict[str, int] = {}
    stopped_reason: str | None = None
    finish_reason: str | None = None

    try:
        for chunk in _iter_with_deadline(stream, extra_kwargs.get("timeout")):
            choices = getattr(chunk, "choices", None) or []
            if choices:
                finish_reason = (
                    getattr(choices[0], "finish_reason", None) or finish_reason
                )
                delta = getattr(choices[0], "delta", None)
                if delta is not None:
                    text = getattr(delta, "content", None)
                    if text:
                        content_parts.append(text)
                        try:
                            if text_delta_callback is not None:
                                callback_result = text_delta_callback(text)
                                if callback_result is False:
                                    stopped_reason = "degenerate_repetition"
                                    close = getattr(stream, "close", None)
                                    if callable(close):
                                        close()
                                    break
                        except Exception:
                            # A misbehaving subscriber must not break the
                            # stream — we still need to drain the iterator
                            # so the underlying HTTP connection closes.
                            pass

                    reasoning_text = getattr(delta, "reasoning_content", None)
                    if reasoning_text:
                        reasoning_parts.append(str(reasoning_text))

                    for tc_delta in getattr(delta, "tool_calls", None) or []:
                        idx = getattr(tc_delta, "index", 0) or 0
                        entry = tool_call_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        tc_id = getattr(tc_delta, "id", None)
                        if tc_id:
                            entry["id"] = tc_id
                        fn = getattr(tc_delta, "function", None)
                        if fn is not None:
                            fn_name = getattr(fn, "name", None)
                            if fn_name:
                                entry["name"] = fn_name
                            fn_args = getattr(fn, "arguments", None)
                            if fn_args:
                                entry["arguments"] += fn_args
                                if tool_input_callback is not None and entry["name"]:
                                    # Same shape as OpenAI and Anthropic: the
                                    # provider streams argument JSON in
                                    # fragments. Forward them so a renderer can
                                    # show the file being written.
                                    try:
                                        callback_result = tool_input_callback(
                                            entry["id"] or f"call_{idx}",
                                            entry["name"],
                                            fn_args,
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

            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = {
                    "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk_usage, "completion_tokens", 0)
                    or 0,
                    "total_tokens": getattr(chunk_usage, "total_tokens", 0) or 0,
                }
                usage.update(_extract_cache_usage(chunk_usage))
    except Exception as exc:
        exc_name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if (
            status in (429, 500, 502, 503, 529)
            or "ServiceUnavailable" in exc_name
            or "RateLimitError" in exc_name
            or "InternalServerError" in exc_name
        ):
            raise ConnectionError(f"{exc_name}: {exc}") from exc
        raise

    tool_calls = []
    for idx in sorted(tool_call_acc.keys()):
        entry = tool_call_acc[idx]
        raw_args = entry["arguments"] or "{}"
        arguments = _parse_tool_arguments(raw_args)
        tool_calls.append(
            ToolCall(
                name=entry["name"],
                arguments=arguments,
                id=entry["id"],
                index=idx,
            ).ensure_id()
        )

    return LLMResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        metadata={
            "model": model,
            "provider": "litellm",
            "streamed": True,
            "finish_reason": finish_reason,
            "prompt_tokens_include_cache": True,
            **({"stream_stopped": stopped_reason} if stopped_reason else {}),
        },
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
        usage=usage,
    )


