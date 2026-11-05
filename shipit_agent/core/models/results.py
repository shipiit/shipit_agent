"""What a run emits as it goes (events, artifacts) and what it returns."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.core.result_subtype import ResultSubtype, result_subtype

from .kinds import EventType
from .message import Message
from .tool_calls import ToolResult


@dataclass(slots=True)
class AgentEvent:
    """One observable moment of a run."""

    type: EventType
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def display_message(self) -> str:
        """The concise, user-facing text for this event."""
        summary = self.payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        if self.message.strip():
            return self.message.strip()
        for key in ("chunk", "delta", "text"):
            value = self.payload.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class Artifact:
    """A file a tool left behind."""

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


@dataclass(slots=True)
class AgentResult:
    """Everything a finished run produced."""

    output: str
    messages: list[Message] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parsed: Any = None
    #: RAG sources cited by this run. Kept so the existing runtime, which
    #: constructs ``AgentResult(rag_sources=…)``, works against the merged
    #: (superset) model rather than raising on an unexpected keyword.
    rag_sources: list[Any] = field(default_factory=list)

    @property
    def subtype(self) -> ResultSubtype:
        """How the run ended: ``success``, or the ``error_*`` reason it stopped short."""
        return result_subtype(self.metadata.get("run_summary"))

    @property
    def is_error(self) -> bool:
        """True when the run stopped before finishing its task."""
        return self.subtype != "success"

    @property
    def steps(self) -> list[AgentEvent]:
        return self.events

    # -- the Claude Agent SDK's ResultMessage fields ----------------------

    @property
    def _run_summary(self) -> dict[str, Any]:
        summary = self.metadata.get("run_summary")
        return summary if isinstance(summary, dict) else {}

    @property
    def num_turns(self) -> int:
        """Model steps the run took."""
        return int(self._run_summary.get("iterations", 0) or 0)

    @property
    def duration_ms(self) -> int:
        """Wall-clock time from the run's first event to its last."""
        if len(self.events) < 2:
            return 0
        return int((self.events[-1].timestamp - self.events[0].timestamp) * 1000)

    @property
    def duration_api_ms(self) -> int:
        """Time spent waiting on the model, retries included."""
        return int(self._run_summary.get("duration_api_ms", 0) or 0)

    @property
    def total_cost_usd(self) -> float | None:
        """Estimated spend from public pricing; ``None`` when unknown."""
        return self._run_summary.get("estimated_cost_usd")

    @property
    def usage(self) -> dict[str, Any]:
        """Token usage summed over the run."""
        return dict(self._run_summary.get("usage") or self.metadata.get("usage") or {})

    @property
    def permission_denials(self) -> list[dict[str, Any]]:
        """Calls that were refused or left waiting for approval, with their input."""
        return [dict(d) for d in self._run_summary.get("permission_denials", [])]

    @property
    def stop_reason(self) -> str | None:
        """Why the model's last response ended, as the provider reported it."""
        return self._run_summary.get("finish_reason")

    @property
    def structured_output(self) -> Any:
        """The answer parsed against ``output_schema``, when one was asked for."""
        return self.parsed

    def summary(self) -> dict[str, Any]:
        """Run metrics computed from the event trace."""
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
        return {
            "duration_seconds": duration,
            "iterations": len(iterations),
            "tool_calls": calls,
            "tool_failures": failures,
            "usage": dict(self.metadata.get("usage", {}) or {}),
            "tools": tools,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "messages": [m.to_dict() for m in self.messages],
            "events": [e.to_dict() for e in self.events],
            "tool_results": [r.to_dict() for r in self.tool_results],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "metadata": dict(self.metadata),
        }
