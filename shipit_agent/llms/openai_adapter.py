from __future__ import annotations

import json
import re
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.llms.litellm_adapter import _extract_reasoning, _serialize_message


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


class OpenAIChatLLM:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
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
        self.client_kwargs = client_kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Any = None,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install `openai` to use OpenAIChatLLM.") from exc

        client = OpenAI(api_key=self.api_key, **self.client_kwargs)
        payload_messages = [_serialize_message(m) for m in messages]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "tools": tools or None,
        }
        # Tell reasoning-capable models to actually emit a thinking block.
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        # Only send tool_choice when we actually have tools to call — OpenAI
        # rejects the parameter otherwise.
        if self.tool_choice and tools:
            kwargs["tool_choice"] = self.tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        if text_delta_callback is not None:
            return self._complete_streaming(client, kwargs, text_delta_callback)

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
                    arguments=json.loads(arguments)
                    if isinstance(arguments, str)
                    else arguments,
                )
            )

        reasoning_content = _extract_reasoning(choice)

        usage: dict[str, int] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }
            # OpenAI does *automatic* prompt caching — no cache_control needed.
            # Surface the cached-prompt portion under the same key the
            # CostTracker reads for Anthropic, so cache reads bill cheaper for
            # OpenAI/OpenAI-compatible providers too. Reasoning models also
            # report reasoning tokens — pass them through when present.
            try:
                details = getattr(response.usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", None) if details else None
                if cached:
                    usage["cache_read_input_tokens"] = int(cached)
                out_details = getattr(
                    response.usage, "completion_tokens_details", None
                )
                reasoning = (
                    getattr(out_details, "reasoning_tokens", None)
                    if out_details
                    else None
                )
                if reasoning:
                    usage["reasoning_tokens"] = int(reasoning)
            except Exception:
                pass

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
        self, client: Any, kwargs: dict[str, Any], on_delta: Any
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
            if status in (429, 500, 502, 503, 529) or "RateLimitError" in exc_name:
                raise ConnectionError(f"{exc_name}: {first_exc}") from first_exc
            try:  # provider may not support stream_options
                stream = client.chat.completions.create(**kwargs, stream=True)
            except Exception:
                raise first_exc from None

        # Some gateways (and test fakes) ignore stream=True and return a plain
        # completion object. Detect that and degrade gracefully: one delta
        # with the full text, same LLMResponse out.
        if hasattr(stream, "choices"):
            choice = stream.choices[0].message
            if choice.content:
                on_delta(choice.content)
            tool_calls = []
            for call in choice.tool_calls or []:
                arguments = call.function.arguments or "{}"
                tool_calls.append(
                    ToolCall(
                        name=call.function.name,
                        arguments=json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments,
                    )
                )
            return LLMResponse(
                content=choice.content or "",
                tool_calls=tool_calls,
                metadata={"model": self.model, "provider": "openai"},
                reasoning_content=_extract_reasoning(choice),
                usage={},
            )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}  # index → {name, arguments}
        usage: dict[str, int] = {}

        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)
                on_delta(text)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(str(reasoning))
            for frag in getattr(delta, "tool_calls", None) or []:
                idx = getattr(frag, "index", 0) or 0
                slot = calls.setdefault(idx, {"name": "", "arguments": ""})
                fn = getattr(frag, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] += fn.name
                    if getattr(fn, "arguments", None):
                        slot["arguments"] += fn.arguments

        tool_calls = []
        for idx in sorted(calls):
            raw = calls[idx]["arguments"] or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = {"_raw": raw}
            tool_calls.append(ToolCall(name=calls[idx]["name"], arguments=arguments))

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            metadata={"model": self.model, "provider": "openai", "streamed": True},
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
