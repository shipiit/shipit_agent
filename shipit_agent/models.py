from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]
EventType = Literal[
    "run_started",
    "reasoning_started",
    "reasoning_completed",
    "step_started",
    "planning_started",
    "planning_completed",
    "tool_called",
    "tool_completed",
    "tool_failed",
    "interactive_request",
    "mcp_attached",
    "llm_retry",
    "tool_retry",
    "run_completed",
    "context_snapshot",
    "rag_sources",
]


@dataclass(slots=True)
class Message:
    role: Role
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "name": self.name,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": dict(self.arguments),
        }


@dataclass(slots=True)
class ToolResult:
    name: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "output": self.output,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AgentEvent:
    type: EventType
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class AgentResult:
    output: str
    messages: list[Message]
    events: list[AgentEvent]
    tool_results: list[ToolResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parsed: Any = None
    rag_sources: list[Any] = field(default_factory=list)

    @property
    def steps(self) -> list[AgentEvent]:
        return self.events

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "messages": [message.to_dict() for message in self.messages],
            "events": [event.to_dict() for event in self.events],
            "tool_results": [tool_result.to_dict() for tool_result in self.tool_results],
            "metadata": dict(self.metadata),
            "rag_sources": [
                src.to_dict() if hasattr(src, "to_dict") else src
                for src in self.rag_sources
            ],
        }


@dataclass(slots=True)
class Artifact:
    name: str
    content: str
    media_type: str = "text/plain"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
        }
