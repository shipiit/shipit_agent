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
    re.compile(r"^o1(-|$)"),          # o1, o1-mini, o1-preview
    re.compile(r"^o3(-|$)"),          # o3, o3-mini
    re.compile(r"^o4(-|$)"),          # o4, o4-mini
    re.compile(r"^gpt-5"),            # gpt-5 family
    re.compile(r"^deepseek-r1"),      # DeepSeek R1 via OpenAI-compatible endpoints
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

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if status in (429, 500, 502, 503, 529) or "ServiceUnavailable" in exc_name or "RateLimitError" in exc_name or "InternalServerError" in exc_name:
                raise ConnectionError(f"{exc_name}: {exc}") from exc
            raise
        choice = response.choices[0].message

        tool_calls = []
        for call in choice.tool_calls or []:
            arguments = call.function.arguments or "{}"
            tool_calls.append(
                ToolCall(
                    name=call.function.name,
                    arguments=json.loads(arguments) if isinstance(arguments, str) else arguments,
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

        return LLMResponse(
            content=choice.content or "",
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "openai",
                **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
            },
            reasoning_content=reasoning_content,
            usage=usage,
        )
