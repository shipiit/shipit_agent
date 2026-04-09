from __future__ import annotations

import json
from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.llms.litellm_adapter import _serialize_message


class OpenAIChatLLM:
    def __init__(self, model: str, api_key: str | None = None, **client_kwargs: Any) -> None:
        self.model = model
        self.api_key = api_key
        self.client_kwargs = client_kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install `openai` to use OpenAIChatLLM.") from exc

        client = OpenAI(api_key=self.api_key, **self.client_kwargs)
        payload_messages = [_serialize_message(m) for m in messages]
        response = client.chat.completions.create(
            model=self.model,
            messages=payload_messages,
            tools=tools or None,
        )
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
        return LLMResponse(
            content=choice.content or "",
            tool_calls=tool_calls,
            metadata={"model": self.model, "provider": "openai"},
        )
