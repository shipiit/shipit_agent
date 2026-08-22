from __future__ import annotations

import re
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.llms.litellm_adapter import (
    _extract_reasoning,
    _iter_with_deadline,
    _parse_tool_arguments,
    _serialize_message,
)


# Models that natively produce reasoning / thinking content.
# Used to auto-pass `reasoning_effort` when the caller doesn't.
_REASONING_MODEL_PATTERNS = [
    re.compile(r"^o1(-|$)"),  # o1, o1-mini, o1-preview
    re.compile(r"^o3(-|$)"),  # o3, o3-mini
    re.compile(r"^o4(-|$)"),  # o4, o4-mini
    re.compile(r"^gpt-5"),  # gpt-5 family
    re.compile(r"^deepseek-r1"),  # DeepSeek R1 via OpenAI-compatible endpoints
]


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return any(p.search(m) for p in _REASONING_MODEL_PATTERNS)


#: Genuine ``OpenAI()`` client-constructor parameters. Anything else a caller
#: passes is a completion/sampling parameter (forwarded to
#: ``chat.completions.create``) or a non-OpenAI flag we drop. Routing all of
#: them to the client used to make it reject ``drop_params`` and silently
#: swallow ``top_p`` (it never reached the model).
_OPENAI_CLIENT_PARAMS = frozenset(
    {
        "base_url",
        "organization",
        "project",
        "timeout",
        "max_retries",
        "default_headers",
        "default_query",
        "http_client",
        "websocket_base_url",
    }
)
#: LiteLLM-only / non-OpenAI knobs that must never reach the OpenAI SDK.
_NON_OPENAI_PARAMS = frozenset(
    {
        "drop_params",
        "modify_params",
        "custom_llm_provider",
        "api_base",
        "aws_region_name",
        "region",
        "prompt_caching",
        "num_retries",
        "aws_bedrock_client",
        "mock_response",
    }
)

# A few OpenAI-compatible gateways acknowledge ``stream=True`` but sometimes
# return a completed response object (Bedrock Mantle can do this after a
# reasoning pass). The provider latency cannot be recovered, but emitting the
# already-buffered text in bounded deltas keeps downstream SSE/rendering
# contracts consistent and avoids one enormous UI update.
_BUFFERED_DELTA_CHARS = 48


def _buffered_deltas(text: str) -> list[str]:
    return [
        text[offset:offset + _BUFFERED_DELTA_CHARS]
        for offset in range(0, len(text), _BUFFERED_DELTA_CHARS)
    ]


def _usage_dict(usage_obj: Any) -> dict[str, int]:
    """Normalize an OpenAI usage object, including automatic-cache counters.

    OpenAI-compatible endpoints — including the Bedrock Mantle / Gemma route —
    do *implicit* prompt caching and report the cached portion under
    ``prompt_tokens_details.cached_tokens`` (and any write under
    ``cache_write_tokens``). Surface those under the same
    ``cache_read_input_tokens`` / ``cache_creation_input_tokens`` keys the cost
    tracker already reads for Anthropic, so cache savings are visible on EVERY
    path — the streaming path (which the agent loop uses) previously dropped
    them, so a real 99%-cached prompt reported as if nothing were cached.
    """
    if not usage_obj:
        return {}
    out: dict[str, int] = {
        "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
    }
    try:
        details = getattr(usage_obj, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached:
            out["cache_read_input_tokens"] = int(cached)
        written = getattr(details, "cache_write_tokens", None) if details else None
        if written:
            out["cache_creation_input_tokens"] = int(written)
        out_details = getattr(usage_obj, "completion_tokens_details", None)
        reasoning = (
            getattr(out_details, "reasoning_tokens", None) if out_details else None
        )
        if reasoning:
            out["reasoning_tokens"] = int(reasoning)
    except Exception:
        pass
    return out


class OpenAIChatLLM:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        # "low" | "medium" | "high" — only applied for reasoning-capable models
        self.reasoning_effort = reasoning_effort or (
            "medium" if _is_reasoning_model(model) else None
        )
        # Pass-through for OpenAI's `tool_choice` kwarg. Set this to "required"
        # to force the model to call at least one tool per turn. Useful with
        # gpt-4o-mini and other lazy models that otherwise return prose-only
        # answers even when tools are clearly needed.
        self.tool_choice = tool_choice
        # Completion controls belong on chat.completions.create(), not on the
        # OpenAI client constructor. Keeping them separate is especially
        # important for OpenAI-compatible endpoints such as Bedrock Mantle.
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Split remaining kwargs: real client config stays for OpenAI(), extra
        # sampling params (top_p, penalties, seed, …) ride the completion call,
        # and non-OpenAI flags (drop_params, …) are dropped.
        self.client_kwargs: dict[str, Any] = {}
        self.extra_completion: dict[str, Any] = {}
        for _k, _v in client_kwargs.items():
            if _k in _OPENAI_CLIENT_PARAMS:
                self.client_kwargs[_k] = _v
            elif _k in _NON_OPENAI_PARAMS:
                continue
            else:
                self.extra_completion[_k] = _v

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Any = None,
        tool_input_callback: Any = None,
        timeout: float | None = None,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install `openai` to use OpenAIChatLLM.") from exc

        client_kwargs = dict(self.client_kwargs)
        if timeout is not None:
            # Per-request override wins over any client-level default.
            client_kwargs["timeout"] = timeout
        client = OpenAI(api_key=self.api_key, **client_kwargs)
        from shipit_agent.llms.capabilities import capabilities_for

        caps = capabilities_for(self.model)
        payload_messages = [
            _serialize_message(
                m, include_reasoning=caps.reasoning_history == "replay"
            )
            for m in messages
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "tools": tools or None,
        }
        # Completion controls are normalized at the adapter boundary. This is
        # the classic Agent path (the graph runtime has its own resolved
        # parameter object), so without this step the declarative capability
        # table was documentation rather than enforcement here.
        requested_params = dict(self.extra_completion)
        if self.reasoning_effort:
            requested_params["reasoning_effort"] = self.reasoning_effort
        if self.max_tokens is not None:
            requested_params["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            requested_params["temperature"] = self.temperature

        from shipit_agent.llms.parameters import resolve_parameters

        resolved_params = resolve_parameters(self.model, requested_params)
        kwargs.update(resolved_params.wire)
        # One shared ladder decides tool_choice (see llms/tool_choice.py); only
        # send it when we have tools, since OpenAI rejects the parameter
        # otherwise. No `default_auto` here — this endpoint does not need the
        # explicit "auto" the mantle route does.
        from shipit_agent.llms.tool_choice import resolve_tool_choice

        choice = resolve_tool_choice(
            tools, require_tool_call=require_tool_call, configured=self.tool_choice
        )
        if choice is not None:
            kwargs["tool_choice"] = choice
        if tools:
            from shipit_agent.llms.capabilities import capabilities_for

            if not capabilities_for(self.model).supports_parallel_tool_calls:
                kwargs["parallel_tool_calls"] = False
        if response_format:
            kwargs["response_format"] = response_format

        if text_delta_callback is not None or tool_input_callback is not None:
            return self._complete_streaming(
                client, kwargs, text_delta_callback, tool_input_callback,
                timeout=client_kwargs.get("timeout"),
            )

        try:
            response = client.chat.completions.create(**kwargs)
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
        choice = response.choices[0].message

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

        reasoning_content = _extract_reasoning(choice)

        usage = _usage_dict(response.usage)

        return LLMResponse(
            content=choice.content or "",
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "openai",
                **(
                    {"reasoning_effort": self.reasoning_effort}
                    if self.reasoning_effort
                    else {}
                ),
            },
            reasoning_content=reasoning_content,
            usage=usage,
        )

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
                        content = content[:emitted_deltas * _BUFFERED_DELTA_CHARS]
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

        for chunk in _iter_with_deadline(stream, timeout):
            if getattr(chunk, "usage", None):
                usage = _usage_dict(chunk.usage)
            if not getattr(chunk, "choices", None):
                continue
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
                slot = calls.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""}
                )
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
                **({"stream_stopped": stopped_reason} if stopped_reason else {}),
            },
            reasoning_content="".join(reasoning_parts) or None,
            usage=usage,
        )


def _bedrock_mantle_base_url(region: str) -> str:
    return f"https://bedrock-mantle.{region}.api.aws/openai/v1"


class BedrockGemmaChatLLM(OpenAIChatLLM):
    """Google **Gemma 4** on Amazon Bedrock — with native agentic tool use.

    Gemma 4 supports *native function calling for agentic workflows*, but on
    Bedrock it is served through the **OpenAI-compatible** ``bedrock-mantle``
    endpoint (not the Converse API that :class:`BedrockChatLLM` uses). So it runs
    on the OpenAI adapter — tool calls, streaming shape, and all — pointed at
    that endpoint with a **Bedrock API key**::

        # 1. Create a Bedrock API key: AWS console → Amazon Bedrock → API keys
        # 2. export AWS_BEARER_TOKEN_BEDROCK=...   (and AWS_REGION_NAME)
        from shipit_agent import Agent
        from shipit_agent.llms import BedrockGemmaChatLLM

        llm = BedrockGemmaChatLLM(model="google.gemma-4-31b", region="us-east-1")
        agent = Agent.with_builtins(llm=llm)
        print(agent.run("What's 2+2? Use a tool if it helps.").output)

    Model ids: ``google.gemma-4-31b`` (dense), ``google.gemma-4-26b-a4b`` (MoE),
    ``google.gemma-4-e2b`` (small). Regions at launch: us-east-1, us-east-2,
    us-west-2, eu-central-1. Multimodal (text + image) too.
    """

    def __init__(
        self,
        model: str = "google.gemma-4-31b",
        *,
        region: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        import os

        resolved_region = (
            region
            or os.getenv("AWS_REGION_NAME")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        resolved_key = api_key or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
        client_kwargs.setdefault(
            "base_url", base_url or _bedrock_mantle_base_url(resolved_region)
        )
        super().__init__(model=model, api_key=resolved_key, **client_kwargs)
