from __future__ import annotations

import os
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall


class AnthropicChatLLM:
    """Native Anthropic Messages API adapter.

    Extracts tool_use blocks as ``ToolCall``s and ``thinking`` blocks as
    ``reasoning_content``, so the runtime can emit ``reasoning_started`` /
    ``reasoning_completed`` events just like the OpenAI and LiteLLM/Bedrock
    adapters do.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        *,
        thinking_budget_tokens: int | None = None,
        prompt_caching: bool = True,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        # When set, Anthropic extended thinking is enabled for every call.
        # Example: AnthropicChatLLM("claude-opus-4-1", thinking_budget_tokens=2048)
        self.thinking_budget_tokens = thinking_budget_tokens
        # Prompt caching marks the stable prefix (tool definitions + system
        # prompt) with ``cache_control: {"type": "ephemeral"}`` breakpoints so
        # Anthropic bills repeated calls' cached prefix at ~10% of input and
        # serves them faster. Always safe on this native adapter (it only ever
        # talks to Anthropic), so it defaults on.
        self.prompt_caching = prompt_caching
        self.client_kwargs = client_kwargs

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Map shipit's Message model to Anthropic's user/assistant blocks."""
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                # System prompts are passed via the top-level `system` kwarg.
                continue
            if message.role == "tool":
                tool_call_id = (
                    message.metadata.get("tool_call_id") or message.name or ""
                )
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": message.content or "",
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant" and message.metadata.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.metadata["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id", ""),
                            "name": call["name"],
                            "input": call.get("arguments", {}),
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
                continue
            converted.append(
                {
                    "role": message.role,
                    "content": message.content or "",
                }
            )
        return converted

    def _fallback_to_bedrock(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system_prompt: str | None,
        metadata: dict[str, Any] | None,
        response_format: dict[str, Any] | None,
    ) -> LLMResponse:
        from shipit_agent.llms.litellm_adapter import BedrockChatLLM

        fallback = BedrockChatLLM(
            model=os.getenv("SHIPIT_BEDROCK_MODEL", "bedrock/openai.gpt-oss-120b-1:0")
        )
        response = fallback.complete(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            metadata=metadata,
            response_format=response_format,
        )
        response.metadata = {
            **dict(response.metadata),
            "provider": "bedrock",
            "fallback_from": "anthropic",
        }
        return response

    def _build_request_kwargs(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system_prompt: str | None,
    ) -> dict[str, Any]:
        """Build the kwargs passed to ``client.messages.create``.

        Split out from :meth:`complete` so the request payload — including
        prompt-caching breakpoints — can be inspected directly in tests
        without mocking the Anthropic SDK.

        When :attr:`prompt_caching` is on, two ``cache_control`` breakpoints
        are added to the stable request prefix:

        * one on the **last** tool definition — Anthropic caches the entire
          ``tools`` array up to and including the marked block, so a single
          breakpoint on the final tool covers every tool def, and
        * one on the (single) **system** prompt block — the string system
          prompt is promoted to the list-of-blocks form so the breakpoint has
          somewhere to live.
        """
        # Translate OpenAI-style tool schemas to Anthropic's flat shape.
        anthropic_tools: list[dict[str, Any]] | None = None
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                )

        system: Any = system_prompt or ""
        if self.prompt_caching:
            # System: convert the string prompt into a single cached text block.
            if system_prompt:
                system = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            # Tools: mark the last tool so the whole array is cached.
            if anthropic_tools:
                anthropic_tools[-1] = {
                    **anthropic_tools[-1],
                    "cache_control": {"type": "ephemeral"},
                }

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": self._convert_messages(messages),
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if self.thinking_budget_tokens:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }
        return kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Any = None,  # noqa: ARG002 — Protocol compliance; streaming TODO
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:
            try:
                return self._fallback_to_bedrock(
                    messages=messages,
                    tools=tools,
                    system_prompt=system_prompt,
                    metadata=metadata,
                    response_format=response_format,
                )
            except Exception:
                raise RuntimeError(
                    "Install `anthropic` to use AnthropicChatLLM."
                ) from exc

        client = anthropic.Anthropic(api_key=self.api_key, **self.client_kwargs)

        kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
        )

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if (
                status in (429, 500, 502, 503, 529)
                or "ServiceUnavailable" in exc_name
                or "RateLimitError" in exc_name
                or "InternalServerError" in exc_name
                or "OverloadedError" in exc_name
            ):
                raise ConnectionError(f"{exc_name}: {exc}") from exc
            raise

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "thinking":
                thinking_parts.append(getattr(block, "thinking", "") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=getattr(block, "name", ""),
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )

        usage: dict[str, int] = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "input_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "output_tokens", 0) or 0,
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            # Prompt-caching usage. These keys match exactly what
            # CostTracker.as_hooks() looks for, so cache reads bill at the
            # cheaper rate automatically. Wrapped defensively: older SDKs
            # simply won't have these attributes (getattr -> 0).
            try:
                cache_read = (
                    getattr(response.usage, "cache_read_input_tokens", 0) or 0
                )
                cache_creation = (
                    getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                )
                if cache_read:
                    usage["cache_read_input_tokens"] = cache_read
                if cache_creation:
                    usage["cache_creation_input_tokens"] = cache_creation
            except Exception:
                pass

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "anthropic",
                **(
                    {"thinking_budget_tokens": self.thinking_budget_tokens}
                    if self.thinking_budget_tokens
                    else {}
                ),
            },
            reasoning_content=("\n".join(thinking_parts) if thinking_parts else None),
            usage=usage,
        )
