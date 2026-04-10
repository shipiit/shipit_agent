from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from shipit_agent.models import Message, ToolCall


@dataclass(slots=True)
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class LLM(Protocol):
    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
