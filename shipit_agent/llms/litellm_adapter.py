from __future__ import annotations

import json
from typing import Any, Callable

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall


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
        if (
            isinstance(block, dict)
            and block.get("type") == "image"
            and isinstance(block.get("source"), dict)
            and block["source"].get("type") == "base64"
        ):
            src = block["source"]
            url = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
            normalized.append({"type": "image_url", "image_url": {"url": url}})
        else:
            normalized.append(block)
    return normalized


def _serialize_message(message: Any) -> dict[str, Any]:
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
    tool_calls = message.metadata.get("tool_calls", [])
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.get("id", f"call_{index}"),
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": json.dumps(item.get("arguments", {}), sort_keys=True),
                },
            }
            for index, item in enumerate(tool_calls, start=1)
        ]
    tool_call_id = message.metadata.get("tool_call_id")
    if message.role == "tool" and tool_call_id:
        payload["tool_call_id"] = tool_call_id
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
        text_delta_callback: Callable[[str], None] | None = None,
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

        payload_messages = [_serialize_message(m) for m in messages]
        request_tools = tools or None
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
        if response_format:
            extra_kwargs["response_format"] = response_format

        if text_delta_callback is not None:
            return _stream_completion(
                completion_fn=completion,
                model=self.model,
                payload_messages=payload_messages,
                tools=request_tools,
                extra_kwargs=extra_kwargs,
                text_delta_callback=text_delta_callback,
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
                    arguments=json.loads(arguments)
                    if isinstance(arguments, str)
                    else arguments,
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


def _stream_completion(
    *,
    completion_fn: Any,
    model: str,
    payload_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    extra_kwargs: dict[str, Any],
    text_delta_callback: Callable[[str], None],
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

    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if choices:
                delta = getattr(choices[0], "delta", None)
                if delta is not None:
                    text = getattr(delta, "content", None)
                    if text:
                        content_parts.append(text)
                        try:
                            text_delta_callback(text)
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
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {"_raw": raw_args}
        tool_calls.append(ToolCall(name=entry["name"], arguments=arguments))

    return LLMResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        metadata={"model": model, "provider": "litellm", "streamed": True},
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


class BedrockChatLLM(LiteLLMChatLLM):
    def __init__(
        self, model: str = "bedrock/openai.gpt-oss-120b-1:0", **completion_kwargs: Any
    ) -> None:
        self._mantle_delegate: Any = None

        # Gemma 4 on Bedrock is served through the OpenAI-compatible
        # `bedrock-mantle` endpoint (with native function calling for agentic
        # use), NOT the Converse API the rest of Bedrock uses. Route it there
        # transparently so callers keep using BedrockChatLLM — pass a
        # `google.gemma-4-*` id and it just works (needs a Bedrock API key in
        # AWS_BEARER_TOKEN_BEDROCK). ``complete()`` forwards to the delegate.
        if "gemma-4" in model.lower():
            from shipit_agent.llms.openai_adapter import BedrockGemmaChatLLM

            mantle_model = model.split("bedrock/", 1)[-1]
            region = completion_kwargs.pop("aws_region_name", None) or (
                completion_kwargs.pop("region", None)
            )
            api_key = completion_kwargs.pop("api_key", None)
            base_url = completion_kwargs.pop("base_url", None)
            self._mantle_delegate = BedrockGemmaChatLLM(
                model=mantle_model,
                region=region,
                api_key=api_key,
                base_url=base_url,
                **completion_kwargs,
            )
            self.model = model
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

    def complete(self, **kwargs: Any) -> LLMResponse:
        # Gemma 4 → OpenAI-compatible mantle endpoint; everything else → Converse.
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
