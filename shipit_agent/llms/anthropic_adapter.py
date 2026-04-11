from __future__ import annotations

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
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        # When set, Anthropic extended thinking is enabled for every call.
        # Example: AnthropicChatLLM("claude-opus-4-1", thinking_budget_tokens=2048)
        self.thinking_budget_tokens = thinking_budget_tokens
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

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.") from exc

        client = anthropic.Anthropic(api_key=self.api_key, **self.client_kwargs)

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

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt or "",
            "messages": self._convert_messages(messages),
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if self.thinking_budget_tokens:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }

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
