from __future__ import annotations

import time
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
    "tool_denied",
    "action_queued",
    "text_delta",
    "usage_tick",
    "interactive_request",
    "mcp_attached",
    "llm_retry",
    "tool_retry",
    "run_completed",
    "run_cancelled",
    "guardrail_triggered",
    "tool_call_healed",
    "context_snapshot",
    "context_compacted",
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
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
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

    def summary(self) -> dict[str, Any]:
        """Run metrics computed from the event trace.

        Returns wall-clock duration, iteration count, token usage, and a
        per-tool breakdown (calls, failures, total time)::

            {
              "duration_seconds": 3.4,
              "iterations": 2,
              "tool_calls": 3,
              "tool_failures": 0,
              "usage": {"input_tokens": 812, "output_tokens": 240},
              "tools": {"bash": {"calls": 2, "failures": 0, "total_ms": 2140.0},
                        "edit_file": {"calls": 1, "failures": 0, "total_ms": 12.0}},
            }
        """
        tools: dict[str, dict[str, Any]] = {}
        iterations: set[Any] = set()
        calls = failures = 0
        for event in self.events:
            payload = event.payload
            if "iteration" in payload:
                iterations.add(payload["iteration"])
            if event.type == "tool_called":
                calls += 1
            if event.type in ("tool_completed", "tool_failed"):
                name = str(payload.get("tool", "?"))
                stats = tools.setdefault(
                    name, {"calls": 0, "failures": 0, "total_ms": 0.0}
                )
                stats["calls"] += 1
                try:
                    stats["total_ms"] += float(payload.get("duration_ms", 0) or 0)
                except (TypeError, ValueError):
                    pass
                if event.type == "tool_failed":
                    stats["failures"] += 1
                    failures += 1
        duration = (
            round(self.events[-1].timestamp - self.events[0].timestamp, 3)
            if len(self.events) >= 2
            else 0.0
        )
        usage = self.metadata.get("usage", {})
        return {
            "duration_seconds": duration,
            "iterations": len(iterations),
            "tool_calls": calls,
            "tool_failures": failures,
            "usage": dict(usage) if isinstance(usage, dict) else {},
            "tools": tools,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "messages": [message.to_dict() for message in self.messages],
            "events": [event.to_dict() for event in self.events],
            "tool_results": [
                tool_result.to_dict() for tool_result in self.tool_results
            ],
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
