from __future__ import annotations

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message


class ShipitLLM:
    """
    Small default LLM stub for local development and tests.
    """

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict] | None = None,
        system_prompt: str | None = None,
        metadata: dict | None = None,
    ) -> LLMResponse:
        last_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        if system_prompt:
            output = f"{system_prompt.strip()}\n\n{last_user_message}".strip()
        else:
            output = last_user_message
        return LLMResponse(content=output)


SimpleEchoLLM = ShipitLLM
