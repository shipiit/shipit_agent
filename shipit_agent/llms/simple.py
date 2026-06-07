from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLMResponse, coerce_messages
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
        response_format: dict | None = None,
        text_delta_callback: Any = None,  # noqa: ARG002 — Protocol compliance
    ) -> LLMResponse:
        # Accept dict messages too (e.g. from ComputerUseAgent).
        coerced = coerce_messages(messages)
        last_user_message = next(
            (
                message.content
                for message in reversed(coerced)
                if message.role == "user"
            ),
            "",
        )
        if system_prompt:
            output = f"{system_prompt.strip()}\n\n{last_user_message}".strip()
        else:
            output = last_user_message
        return LLMResponse(content=output)


SimpleEchoLLM = ShipitLLM
