from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message


class AnthropicChatLLM:
    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 2048, **client_kwargs: Any) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
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
            import anthropic
        except ImportError as exc:
            raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.") from exc

        client = anthropic.Anthropic(api_key=self.api_key, **self.client_kwargs)
        converted_messages = [
            {"role": message.role if message.role != "tool" else "assistant", "content": message.content}
            for message in messages
            if message.role != "system"
        ]
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt or "",
            messages=converted_messages,
        )
        text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return LLMResponse(
            content="".join(text_parts),
            metadata={"model": self.model, "provider": "anthropic"},
        )
