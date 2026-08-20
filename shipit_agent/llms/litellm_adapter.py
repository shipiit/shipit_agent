from __future__ import annotations

import json
import queue
import re
import threading
import time
from typing import Any, Callable

from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.bedrock_token import (
    BedrockTokenError,
    existing_bearer_token,
    generate_bearer_token,
)
from shipit_agent.models import Message, ToolCall


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Parse provider arguments without turning one bad call into a dead run."""
    if isinstance(arguments, dict):
        return arguments
    raw = arguments or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"_raw": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_raw": str(raw)}


def _normalize_content(content: Any) -> Any:
    """Make multimodal content portable across providers.

    Callers like ``ComputerUseAgent`` build Anthropic-shape image blocks
    (``{"type": "image", "source": {"type": "base64", ...}}``). LiteLLM (and
    OpenAI) speak the ``image_url`` shape, so translate base64 image blocks to a
    ``data:`` URL. Plain-string content and already-``image_url`` blocks pass
    through unchanged.
    """
    if not isinstance(content, list):
        return content
    normalized: list[Any] = []
    for block in content:
        source = block.get("source") if isinstance(block, dict) else None
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type == "image" and isinstance(source, dict):
            if source.get("type") == "base64":
                url = (
                    f"data:{source.get('media_type', 'image/png')};"
                    f"base64,{source.get('data', '')}"
                )
                normalized.append({"type": "image_url", "image_url": {"url": url}})
                continue
            if source.get("type") == "url":
                # A URL-source Anthropic block forwarded untranslated is
                # rejected by every OpenAI-shaped endpoint.
                normalized.append(
                    {"type": "image_url", "image_url": {"url": source.get("url", "")}}
                )
                continue
        if block_type == "document" and isinstance(source, dict):
            # OpenAI-shaped endpoints have no document block; degrade to a
            # named placeholder rather than forwarding a rejected shape.
            name = source.get("url") or source.get("media_type") or "attached"
            normalized.append(
                {"type": "text", "text": f"[document attachment: {name} — "
                 "content not displayable on this provider]"}
            )
            continue
        if block_type in ("audio", "video"):
            normalized.append(
                {"type": "text", "text": f"[{block_type} attachment — "
                 "not supported on this provider]"}
            )
            continue
        normalized.append(block)
    return normalized


def _serialize_message(
    message: Any, *, include_reasoning: bool = False
) -> dict[str, Any]:
    # Accept raw dict messages (e.g. from ComputerUseAgent) as well as Message
    # objects — a dict is already in OpenAI message shape; just normalize media.
    if isinstance(message, dict):
        payload: dict[str, Any] = {
            "role": message.get("role", "user"),
            "content": _normalize_content(message.get("content", "")),
        }
        if message.get("name"):
            payload["name"] = message["name"]
        if message.get("tool_calls"):
            payload["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            payload["tool_call_id"] = message["tool_call_id"]
        return payload

    payload = {
        "role": message.role,
        "content": _normalize_content(message.content),
        **({"name": message.name} if message.name else {}),
    }
    typed_calls = getattr(message, "tool_calls", None) or []
    tool_calls = (
        [call.to_dict() for call in typed_calls]
        if typed_calls
        else message.metadata.get("tool_calls", [])
    )
    # A tool's own metadata is merged onto its message, so any tool can land
    # a value here. Only a list of records is meaningful; anything else is a
    # key collision and must not take the request down.
    if not isinstance(tool_calls, (list, tuple)):
        tool_calls = []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.get("id", f"call_{index}"),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": json.dumps(item.get("arguments", {}), sort_keys=True),
                },
            }
            for index, item in enumerate(tool_calls, start=1)
            if isinstance(item, dict)
        ]
    tool_call_id = (
        getattr(message, "tool_call_id", None)
        or message.metadata.get("tool_call_id")
    )
    if message.role == "tool" and tool_call_id:
        payload["tool_call_id"] = tool_call_id
    if include_reasoning and message.role == "assistant":
        reasoning = message.metadata.get("reasoning_content")
        if reasoning:
            payload["reasoning_content"] = reasoning
    return payload


def _is_anthropic_model(model: str) -> bool:
    """True for Anthropic-family models (direct, on Bedrock, or on Vertex).

    Only these accept Anthropic ``cache_control`` breakpoints, which LiteLLM
    forwards to the Messages API and translates to Bedrock ``cachePoint``
    blocks for ``bedrock/anthropic.*`` models. Any other provider would reject
    the unknown field, so caching is gated behind this predicate.
    """
    m = model.lower()
    return "anthropic" in m or "claude" in m


def _with_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``block`` with an ephemeral cache breakpoint."""
    return {**block, "cache_control": {"type": "ephemeral"}}


def _apply_prompt_caching(
    payload_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Inject ``cache_control`` breakpoints on the system message + last tool.

    Returns new lists; the caller's ``tools`` / message objects are never
    mutated in place (they are reused across calls). The system message's
    string content is promoted to Anthropic's list-of-blocks form so the
    breakpoint has a home; LiteLLM forwards this verbatim to the Anthropic /
    Bedrock-Anthropic backends.
    """
    new_messages: list[dict[str, Any]] = []
    system_marked = False
    for msg in payload_messages:
        if msg.get("role") == "system" and not system_marked:
            content = msg.get("content")
            if isinstance(content, str) and content:
                new_messages.append(
                    {
                        **msg,
                        "content": [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                )
                system_marked = True
                continue
            if isinstance(content, list) and content:
                marked = list(content)
                last = marked[-1]
                if isinstance(last, dict):
                    marked[-1] = _with_cache_control(last)
                    new_messages.append({**msg, "content": marked})
                    system_marked = True
                    continue
        new_messages.append(msg)

    new_tools = tools
    if tools:
        new_tools = list(tools)
        new_tools[-1] = _with_cache_control(new_tools[-1])

    # Third breakpoint: the last message, so the whole conversation prefix
    # is cached. Each step of an agent run extends the previous request;
    # without this marker the growing history is re-billed as uncached
    # input every iteration. String content is promoted to the block form
    # so the marker has a home.
    if new_messages:
        last_msg = new_messages[-1]
        if last_msg.get("role") != "system":
            content = last_msg.get("content")
            if isinstance(content, str) and content:
                new_messages[-1] = {
                    **last_msg,
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            elif isinstance(content, list) and content and isinstance(content[-1], dict):
                marked = list(content)
                marked[-1] = _with_cache_control(marked[-1])
                new_messages[-1] = {**last_msg, "content": marked}

    return new_messages, new_tools


class LiteLLMChatLLM:
    def __init__(
        self, model: str, *, prompt_caching: bool = True, **completion_kwargs: Any
    ) -> None:
        self.model = model
        # Forward Anthropic ``cache_control`` breakpoints through LiteLLM for
        # Anthropic-family models (incl. Bedrock/Vertex Claude). Gated per-call
        # on the model id so non-Anthropic providers never see the field.
        # Extracted as an explicit kwarg so it is NOT forwarded into
        # ``litellm.completion`` (which would reject the unknown argument).
        self.prompt_caching = prompt_caching
        self.completion_kwargs = completion_kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Callable[[str], bool | None] | None = None,
        tool_input_callback: Callable[[str, str, str], None] | None = None,
        timeout: float | None = None,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        """Run a chat completion.

        If ``text_delta_callback`` is provided, switches to streaming mode and
        invokes the callback synchronously for each text chunk as it arrives.
        Returns the same ``LLMResponse`` shape in both modes so callers don't
        branch — the runtime just opts in by passing the callback.
        """
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError("Install `litellm` to use LiteLLMChatLLM.") from exc

        from shipit_agent.llms.capabilities import capabilities_for

        caps = capabilities_for(self.model)
        payload_messages = [
            _serialize_message(
                m, include_reasoning=caps.reasoning_history == "replay"
            )
            for m in messages
        ]
        request_tools = tools or None
        # Inline `$ref`/`$defs` and dialect-sanitize each tool's parameter schema
        # BEFORE it goes on the wire. Pydantic/FastMCP MCP servers emit `$defs` +
        # `$ref` for nested argument models; OpenAI tolerates it, but a strict
        # OpenAI-*compatible* validator like Bedrock Mantle often does not —
        # simple tools keep working, nested ones fail quietly, and the model
        # reads as stupid rather than blocked. Cached and never-raising.
        if request_tools:
            try:
                from shipit_agent.llms.capabilities import capabilities_for
                from shipit_agent.llms.schema_prep import prepare_tool_schema

                # `$ref` inlining is dialect-independent; the dialect only tunes
                # the sanitize step. Default to the strictest (openai_strict) so
                # Bedrock Mantle gets clean schemas even where the capability
                # row carries no dialect.
                _dialect = getattr(
                    capabilities_for(self.model), "schema_dialect", "openai_strict"
                ) or "openai_strict"
                request_tools = [
                    prepare_tool_schema(t, dialect=_dialect) for t in request_tools
                ]
            except Exception:  # noqa: BLE001 — schema prep must never break a call
                pass
        # Add prompt-caching breakpoints for Anthropic-family models. Guarded so
        # non-Anthropic providers never receive the unsupported field and
        # nothing crashes if message/tool shapes are unexpected.
        if self.prompt_caching and _is_anthropic_model(self.model):
            try:
                payload_messages, request_tools = _apply_prompt_caching(
                    payload_messages, request_tools
                )
            except Exception:
                # Defensive: never let caching break a real call.
                pass

        extra_kwargs = dict(self.completion_kwargs)
        # Per-model parameter hygiene: drop params this model rejects (Gemma on
        # Mantle takes temperature/top_p only — top_k, penalties, logprobs,
        # thinking_budget all 400) and fill AWS-recommended defaults the caller
        # left unset (Gemma: temperature=1.0, top_p=0.95). Unknown models get a
        # permissive default that strips/fills nothing.
        try:
            from shipit_agent.llms.capabilities import (
                apply_recommended_params,
                sanitize_params,
            )

            accepted, _dropped = sanitize_params(self.model, extra_kwargs)
            extra_kwargs = apply_recommended_params(self.model, accepted)
        except Exception:  # noqa: BLE001 — param hygiene must never break a call
            pass
        # Host params are instructions to shipit's own compactor/loop, not fields
        # any provider knows — forwarding one is a 400 naming a parameter never
        # aimed at the model. Strip them before the wire.
        for _host in (
            "max_context_tokens", "file_token_limit", "fileTokenLimit",
            "max_iterations", "max_tool_output_chars", "context_window_tokens",
        ):
            extra_kwargs.pop(_host, None)
        if response_format:
            extra_kwargs["response_format"] = response_format
        if request_tools and require_tool_call:
            extra_kwargs["tool_choice"] = "required"
        if timeout is not None:
            # LiteLLM accepts a per-call `timeout` and forwards it to every
            # provider it wraps; the per-request value wins.
            extra_kwargs["timeout"] = timeout
        # When tools are offered, tell the model it MAY call one ("auto"). Most
        # providers assume this, but some OpenAI-compatible endpoints — notably
        # Bedrock's Gemma (`bedrock-mantle`) route, per AWS's own examples — only
        # engage function calling reliably when `tool_choice` is sent
        # explicitly; without it the model narrates the call as prose instead of
        # emitting a structured one. A caller can override ("required"/"none")
        # via ``completion_kwargs``.
        if request_tools and "tool_choice" not in extra_kwargs:
            extra_kwargs["tool_choice"] = "auto"
        if request_tools and "parallel_tool_calls" not in extra_kwargs:
            from shipit_agent.llms.capabilities import capabilities_for

            if not capabilities_for(self.model).supports_parallel_tool_calls:
                extra_kwargs["parallel_tool_calls"] = False

        # Strip parameters this model family is known to reject, rather than
        # letting the provider 400 mid-turn on a field the caller never set
        # deliberately (`temperature` usually arrives from a default). Blocks
        # nothing for an unmatched model. See llms/capabilities.py.
        extra_kwargs, _dropped = sanitize_params(self.model, extra_kwargs)

        if text_delta_callback is not None or tool_input_callback is not None:
            return _stream_completion(
                completion_fn=completion,
                model=self.model,
                payload_messages=payload_messages,
                tools=request_tools,
                extra_kwargs=extra_kwargs,
                text_delta_callback=text_delta_callback,
                tool_input_callback=tool_input_callback,
            )

        try:
            response = completion(
                model=self.model,
                messages=payload_messages,
                tools=request_tools,
                **extra_kwargs,
            )
        except Exception as exc:
            # Re-raise transient provider errors (503, 429, 500) as
            # ConnectionError so the runtime's RetryPolicy can catch them.
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
        message = response.choices[0].message
        tool_calls = []
        for call in getattr(message, "tool_calls", []) or []:
            arguments = call.function.arguments or "{}"
            tool_calls.append(
                ToolCall(
                    name=call.function.name,
                    arguments=_parse_tool_arguments(arguments),
                    id=str(getattr(call, "id", "") or ""),
                )
            )
        reasoning_content = _extract_reasoning(message)

        usage: dict[str, int] = {}
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
            usage.update(_extract_cache_usage(u))

        return LLMResponse(
            content=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
            metadata={"model": self.model, "provider": "litellm"},
            reasoning_content=reasoning_content,
            usage=usage,
        )


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
    tool_input_callback: Callable[[str, str, str], None] | None = None,
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

    try:
        for chunk in _iter_with_deadline(stream, extra_kwargs.get("timeout")):
            choices = getattr(chunk, "choices", None) or []
            if choices:
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
                                        tool_input_callback(
                                            entry["id"] or f"call_{idx}",
                                            entry["name"],
                                            fn_args,
                                        )
                                    except Exception:
                                        pass

            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = {
                    "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
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
            **({"stream_stopped": stopped_reason} if stopped_reason else {}),
        },
        reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
        usage=usage,
    )


def _extract_cache_usage(usage_obj: Any) -> dict[str, int]:
    """Best-effort extraction of prompt-cache token counts from a usage object.

    LiteLLM normalises providers inconsistently, so several shapes are tried:

    * Anthropic-style attributes promoted onto ``usage``
      (``cache_read_input_tokens`` / ``cache_creation_input_tokens``),
    * OpenAI-style ``usage.prompt_tokens_details.cached_tokens``.

    The returned keys (``cache_read_input_tokens`` /
    ``cache_creation_input_tokens``) are exactly what ``CostTracker.as_hooks``
    reads, so cache reads bill at the discounted rate automatically. Returns an
    empty dict (and never raises) when no cache info is present.
    """
    out: dict[str, int] = {}
    try:
        cache_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
        if not cache_read:
            details = getattr(usage_obj, "prompt_tokens_details", None)
            if details is not None:
                cache_read = getattr(details, "cached_tokens", 0) or 0
        if cache_read:
            out["cache_read_input_tokens"] = int(cache_read)
        if cache_creation:
            out["cache_creation_input_tokens"] = int(cache_creation)
    except Exception:
        return {}
    return out


def _extract_reasoning(message: Any) -> str | None:
    """Pull thinking/reasoning content out of a litellm response message.

    Handles multiple provider shapes:
    - OpenAI o-series / gpt-oss / DeepSeek R1 → `message.reasoning_content`
    - Anthropic Claude extended thinking → `message.thinking_blocks[*].thinking`
    - Bedrock Llama 4 direct → raw `{"type": "reasoning", "content": ...}` dicts
    - Fallback → inspect `message.model_dump()` for any of the above keys
    """
    # 1. Flat reasoning_content attribute (most providers via litellm)
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)

    # 2. Anthropic-style thinking blocks
    thinking_blocks = getattr(message, "thinking_blocks", None)
    if thinking_blocks:
        parts: list[str] = []
        for block in thinking_blocks:
            if isinstance(block, dict):
                text = block.get("thinking") or block.get("text") or ""
            else:
                text = getattr(block, "thinking", "") or getattr(block, "text", "")
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)

    # 3. Fallback — inspect the pydantic/dict form
    dump: dict[str, Any] | None = None
    if hasattr(message, "model_dump"):
        try:
            dump = message.model_dump()
        except Exception:
            dump = None
    if dump:
        if dump.get("reasoning_content"):
            return str(dump["reasoning_content"])
        blocks = dump.get("thinking_blocks") or []
        parts = [
            b.get("thinking") or b.get("text") or ""
            for b in blocks
            if isinstance(b, dict)
        ]
        parts = [p for p in parts if p]
        if parts:
            return "\n".join(parts)

    return None


#: Bedrock Mantle model ids in every spelling seen in the wild — ``gemma-4``,
#: ``gemma4``, ``gemma_4`` — and any major version from 4 up. Matching the
#: literal ``"gemma-4"`` alone silently routed ``gemma4-31b`` to the Converse
#: API, which cannot serve it, so the same model worked or failed depending on
#: how its id was punctuated.
_MANTLE_MODEL_RE = re.compile(r"gemma[-_]?([4-9]|\d{2,})")


def _litellm_supports_bedrock_mantle() -> bool:
    """Does the installed LiteLLM ship the native ``bedrock_mantle`` provider?

    Added in LiteLLM ~1.84 (mirrors AWS's Bedrock Mantle OpenAI-compatible
    surface — https://docs.litellm.ai/docs/providers/bedrock_mantle). Feature-
    detected rather than version-compared so forks and backports behave.
    """
    try:
        import litellm  # type: ignore

        return any("bedrock_mantle" == p.value for p in litellm.LlmProviders)
    except Exception:
        return False


class BedrockChatLLM(LiteLLMChatLLM):
    def __init__(
        self, model: str = "bedrock/openai.gpt-oss-120b-1:0", **completion_kwargs: Any
    ) -> None:
        self._mantle_delegate: Any = None

        # Bedrock Mantle models (Gemma 4 et al.) are served through the
        # OpenAI-compatible `bedrock-mantle` endpoint, NOT the Converse API
        # the rest of Bedrock uses. Accept the id in any spelling callers
        # use: `bedrock_mantle/google.gemma-4-…`, `bedrock/google.gemma-4-…`,
        # or a bare `google.gemma-4-…`.
        #
        # Preferred route: LiteLLM's native `bedrock_mantle/` provider
        # (https://docs.litellm.ai/docs/providers/bedrock_mantle) — but it
        # authenticates with a Bedrock API key as a BEARER token, not SigV4,
        # so it is only taken when such a key is actually present. A SigV4-
        # only environment falls through to the shim below (verified live:
        # the native route 401s without BEDROCK_MANTLE_API_KEY).
        lowered = model.lower()
        is_mantle = bool(_MANTLE_MODEL_RE.search(lowered)) or lowered.startswith(
            "bedrock_mantle/"
        )
        # Accept every spelling of the Bedrock API key. AWS documents
        # ``AWS_BEARER_TOKEN_BEDROCK``; that is also the one the OpenAI shim
        # below actually reads and the one this package's own docstring tells
        # users to export. Checking only ``BEDROCK_MANTLE_API_KEY`` here meant a
        # correctly-configured user was pushed off the preferred native route
        # onto the shim.
        mantle_key = completion_kwargs.get("api_key") or existing_bearer_token()
        # A SigV4-only environment (access keys, a profile, an SSO login, an
        # instance or task role — the common AWS setup) has no bearer token, and
        # both mantle routes need one. Rather than build an adapter that 401s on
        # its first call, derive the token: a short-term Bedrock API key *is* a
        # SigV4-presigned request, so the credentials already present are
        # sufficient. See shipit_agent/llms/bedrock_token.py.
        if is_mantle and not mantle_key:
            region_hint = completion_kwargs.get(
                "aws_region_name"
            ) or completion_kwargs.get("region")
            try:
                mantle_key = generate_bearer_token(region=region_hint)
            except BedrockTokenError as exc:
                raise RuntimeError(
                    f"{model!r} is a Bedrock Mantle model, served over the "
                    "OpenAI-compatible bedrock-mantle endpoint. It authenticates "
                    "with a Bedrock API key sent as a BEARER token, not with "
                    "SigV4 request signing, and no key was found or derivable.\n"
                    f"  Underlying cause: {exc}\n"
                    "  Either export AWS_BEARER_TOKEN_BEDROCK=... (AWS console → "
                    "Amazon Bedrock → API keys), or configure ordinary AWS "
                    "credentials plus a region and one will be derived for you.\n"
                    "SigV4-authenticated Bedrock models (Anthropic, Nova, Llama, "
                    "Mistral, Titan) are unaffected."
                ) from exc

        has_mantle_key = bool(mantle_key)
        if has_mantle_key:
            # Both routes read the key from `api_key`; pass the derived token
            # explicitly rather than exporting it, so a token minted for this
            # adapter never leaks into the process environment or into any other
            # library that happens to read that variable.
            completion_kwargs["api_key"] = mantle_key

        # Always use the OpenAI-compatible shim (`.../openai/v1`) for mantle
        # models — the route AWS documents for Gemma 4, which returns NATIVE
        # structured `tool_calls`. LiteLLM's native `bedrock_mantle/` provider is
        # deliberately NOT used: on this endpoint it 400s
        # `model '…' isn't supported on this route` for the Gemma ids.
        # ``complete()`` forwards to the delegate.
        if is_mantle:
            from shipit_agent.llms.openai_adapter import BedrockGemmaChatLLM

            mantle_model = model.split("/", 1)[-1] if "/" in model else model
            region = completion_kwargs.pop("aws_region_name", None) or (
                completion_kwargs.pop("region", None)
            )
            api_key = completion_kwargs.pop("api_key", None)
            base_url = completion_kwargs.pop("base_url", None)
            # Caching is hard-coded off below; drop any caller-supplied
            # `prompt_caching` so it can't collide with that keyword.
            completion_kwargs.pop("prompt_caching", None)
            self._mantle_delegate = BedrockGemmaChatLLM(
                model=mantle_model,
                region=region,
                api_key=api_key,
                base_url=base_url,
                **completion_kwargs,
            )
            # Initialise the base class even though `complete()` delegates.
            # Returning early left the instance without `prompt_caching` and
            # `completion_kwargs`, so a `BedrockChatLLM` that reports itself as
            # one did not carry the attributes every other instance has —
            # `doctor` only avoids an AttributeError because it happens to
            # guard with hasattr, and it then reports the wrong cache mode.
            # Caching stays off: the mantle endpoint is not Anthropic-family.
            super().__init__(model=model, prompt_caching=False, **completion_kwargs)
            return

        # Bedrock's Anthropic path requires strict tool_use/tool_result id
        # pairing. The shipit_agent Message model doesn't carry tool-call IDs,
        # so we let litellm patch the request on our behalf (inserts dummy
        # assistant turns + filler tool_results where needed). Without this,
        # Bedrock-Claude rejects multi-step tool runs with "Expected
        # toolResult blocks ... for Ids: <uuid>".
        #
        # Other Bedrock model families (Nova, Titan, Llama, Mistral) reject
        # `modify_params` as a malformed input — so only apply it for
        # Anthropic-on-Bedrock. Same story for the global flag.
        is_anthropic = "anthropic" in model.lower() or "claude" in model.lower()
        if is_anthropic:
            completion_kwargs.setdefault("modify_params", True)
        super().__init__(model=model, **completion_kwargs)
        if is_anthropic:
            try:
                import litellm  # type: ignore

                litellm.modify_params = True
            except Exception:
                pass

    def complete(
        self,
        *,
        text_delta_callback: Callable[[str], bool | None] | None = None,
        tool_input_callback: Callable[[str, str, str], None] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # Gemma 4 → OpenAI-compatible mantle endpoint; everything else →
        # Converse. `text_delta_callback` and `tool_input_callback` are named
        # explicitly rather than left to **kwargs so capability sniffing
        # (`accepts_text_delta_callback`, which requires the parameter by name
        # and does NOT count a bare **kwargs) can see them. Both delegates
        # support both callbacks; an unnamed kwarg would make the runtime treat
        # this adapter as non-streaming and never pass the callback — silently
        # disabling token-by-token output on the mantle route.
        if text_delta_callback is not None:
            kwargs["text_delta_callback"] = text_delta_callback
        if tool_input_callback is not None:
            kwargs["tool_input_callback"] = tool_input_callback
        if self._mantle_delegate is not None:
            return self._mantle_delegate.complete(**kwargs)
        return super().complete(**kwargs)


class GeminiChatLLM(LiteLLMChatLLM):
    def __init__(
        self, model: str = "gemini/gemini-1.5-pro", **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class VertexAIChatLLM(LiteLLMChatLLM):
    """Google Vertex AI adapter.

    Supports the full Vertex AI model catalog — Gemini, Claude-on-Vertex,
    Llama-on-Vertex, text-bison, etc. Accepts a service-account JSON file
    for authentication, plus the required ``project_id`` and ``location``.

    Example::

        llm = VertexAIChatLLM(
            model="vertex_ai/gemini-1.5-pro",
            service_account_file="/path/to/sa.json",
            project_id="my-gcp-project",
            location="us-central1",
        )

    If ``service_account_file`` is provided, the adapter sets
    ``GOOGLE_APPLICATION_CREDENTIALS`` in the process environment before the
    first ``complete()`` call, so LiteLLM can pick it up automatically.
    Alternatively, set ``GOOGLE_APPLICATION_CREDENTIALS`` in your shell or
    ``.env`` and omit ``service_account_file``.
    """

    def __init__(
        self,
        model: str = "vertex_ai/gemini-1.5-pro",
        *,
        service_account_file: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        **completion_kwargs: Any,
    ) -> None:
        import os as _os

        # Wire the service-account JSON file into the environment so LiteLLM
        # and google-auth can find it. Only sets if not already set.
        if service_account_file:
            _os.environ.setdefault(
                "GOOGLE_APPLICATION_CREDENTIALS", service_account_file
            )

        # Vertex AI requires project + location. LiteLLM reads these from
        # per-call kwargs OR from env vars. We inject into kwargs when
        # provided so they can't be silently dropped by env drift.
        if project_id:
            completion_kwargs.setdefault("vertex_project", project_id)
        if location:
            completion_kwargs.setdefault("vertex_location", location)

        self.service_account_file = service_account_file
        self.project_id = project_id
        self.location = location
        super().__init__(model=model, **completion_kwargs)


class LiteLLMProxyChatLLM(LiteLLMChatLLM):
    """Adapter for self-hosted LiteLLM proxy servers (``litellm --config``).

    Use this when you run your own LiteLLM proxy — typically as a centralized
    gateway for multiple teams — and want every shipit agent to point at it.
    The proxy handles credential management, rate limiting, routing, and
    cost tracking; shipit just talks OpenAI-compatible HTTP to it.

    Example::

        llm = LiteLLMProxyChatLLM(
            model="gpt-4o-mini",                        # whatever the proxy routes to
            api_base="https://litellm.my-company.internal",
            api_key="sk-proxy-token",
            custom_llm_provider="openai",               # the proxy speaks OpenAI format
        )

    Defaults to ``custom_llm_provider="openai"`` because the LiteLLM proxy
    always exposes an OpenAI-compatible API regardless of the upstream
    provider. Override only if you're pointing at a non-LiteLLM proxy.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        custom_llm_provider: str = "openai",
        **completion_kwargs: Any,
    ) -> None:
        if api_base:
            completion_kwargs.setdefault("api_base", api_base)
        if api_key:
            completion_kwargs.setdefault("api_key", api_key)
        completion_kwargs.setdefault("custom_llm_provider", custom_llm_provider)
        self.api_base = api_base
        self.api_key = api_key
        self.custom_llm_provider = custom_llm_provider
        super().__init__(model=model, **completion_kwargs)


class GroqChatLLM(LiteLLMChatLLM):
    def __init__(
        self, model: str = "groq/llama-3.3-70b-versatile", **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class TogetherChatLLM(LiteLLMChatLLM):
    def __init__(
        self,
        model: str = "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
        **completion_kwargs: Any,
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class OllamaChatLLM(LiteLLMChatLLM):
    def __init__(
        self, model: str = "ollama/llama3.1", **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)
