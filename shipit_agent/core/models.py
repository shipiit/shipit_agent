"""The values that move through a run.

The one change here that matters more than the rest: **a tool call carries its
own id**. Providers correlate a call to its result by id — Bedrock rejects a
multi-step run with "Expected toolResult blocks for Ids: …" when the pairing is
absent — and an id that lives in a loose ``metadata`` dict is an id that the
type system cannot check, that a helper holding only a :class:`ToolCall` cannot
reach, and that every adapter has to rediscover.

Carrying it as a field has three consequences worth naming:

* **No history rewriting.** With correct pairing emitted directly, the SDK no
  longer has to patch requests by inserting filler turns. Those insertions
  polluted context, cost tokens on every subsequent turn, and — since implicit
  prompt caching keys on a stable prefix — silently destroyed every cache hit
  for the rest of the conversation.
* **Parallel calls are unambiguous.** Two concurrent calls to the same tool are
  distinguishable, which they are not when a name is the only handle.
* **Runs can be resumed.** A checkpoint can name the call it stopped on.

Ids are also mirrored into ``metadata`` on serialisation, so adapters written
against the old shape keep working through one release. Read the field; write
both.
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

__all__ = [
    "Role",
    "EventType",
    "Message",
    "ToolCall",
    "ToolResult",
    "AgentEvent",
    "AgentResult",
    "Artifact",
    "new_tool_call_id",
    "pair_calls_and_results",
]

Role = Literal["system", "user", "assistant", "tool"]

EventType = Literal[
    "run_started",
    "iteration_started",
    "reasoning_started",
    "reasoning_delta",
    "reasoning_completed",
    "text_delta",
    "tool_group_started",
    "tool_called",
    "tool_input_delta",
    "tool_output_delta",
    "tool_completed",
    "tool_failed",
    "tool_denied",
    "tool_arguments_rejected",
    "tool_group_completed",
    "skill_catalog_ready",
    "skill_loaded",
    "mcp_attached",
    "tools_discovered",
    "tools_rebound",
    "subagent_started",
    "subagent_event",
    "subagent_completed",
    "context_compaction_started",
    "context_compacted",
    "approval_required",
    "checkpoint_saved",
    "usage_tick",
    "llm_retry",
    "final_answer",
    "run_summary",
    "run_completed",
    "run_failed",
    "run_cancelled",
]

_counter = itertools.count(1)


def new_tool_call_id(prefix: str = "call") -> str:
    """A locally-unique id, for providers that do not supply one.

    Short and readable rather than a bare UUID, because these ids appear in
    logs, traces and error messages, and a human comparing two of them at a
    glance is a routine part of debugging a parallel tool batch.
    """
    return f"{prefix}_{next(_counter):03d}_{uuid.uuid4().hex[:8]}"


@dataclass(slots=True)
class ToolCall:
    """A model's request to run one tool."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: Provider-supplied id, or one generated at parse time. Never empty once
    #: the call has been through :meth:`ensure_id`.
    id: str = ""
    #: Position within its batch, so a UI can order parallel calls stably.
    index: int = 0

    def ensure_id(self) -> "ToolCall":
        """Fill a missing id in place and return self, for fluent parsing."""
        if not self.id:
            self.id = new_tool_call_id()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": dict(self.arguments),
            "index": self.index,
        }

    def to_wire(self) -> dict[str, Any]:
        """OpenAI-shaped ``tool_calls`` entry."""
        import json

        return {
            "id": self.id or new_tool_call_id(),
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, sort_keys=True, default=str),
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, index: int = 0) -> "ToolCall":
        return cls(
            name=str(data.get("name", "")),
            arguments=dict(data.get("arguments") or {}),
            id=str(data.get("id", "")),
            index=int(data.get("index", index)),
        ).ensure_id()


@dataclass(slots=True)
class ToolResult:
    """What a tool produced, bound to the call that asked for it."""

    name: str
    output: str
    #: The id of the :class:`ToolCall` this answers. Required for correct
    #: pairing; empty only for results synthesised outside a call.
    tool_call_id: str = ""
    #: Errors are results, not exceptions — the model must be able to recover
    #: from a failed tool without the run ending.
    is_error: bool = False
    #: True when the model-visible text was shortened. Truncation is always
    #: visible, so the model knows to fetch the rest rather than assuming it
    #: saw everything.
    truncated: bool = False
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Optional semantic extract supplied by the tool. ``output`` remains the
    #: complete canonical value; only this compact view is sent to the model.
    model_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "output": self.output,
            "tool_call_id": self.tool_call_id,
            "is_error": self.is_error,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
            "model_text": self.model_text,
        }


@dataclass(slots=True)
class ToolCallPart:
    """A tool call and its result, as one indivisible unit — the *collapsed*
    storage shape (see :mod:`shipit_agent.chat_history`).

    The output lives on the call rather than in a separate message so the two
    cannot be separated by a partial write, a compaction boundary, or a history
    truncation. That separation is the only thing request-patching (
    ``modify_params``) ever repaired.
    """

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    output: str | None = None  # None = still running (paused / in flight)
    is_error: bool = False
    truncated: bool = False
    duration_ms: float = 0.0
    #: Set when paused for human review. Its presence is what a UI renders
    #: approval controls from.
    approval: dict[str, Any] | None = None
    input_validation_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.output is not None or self.is_error


@dataclass(slots=True)
class TextPart:
    """Prose inside a collapsed turn, with the calls it relates to."""

    text: str
    #: Which calls this prose relates to. Without it, "I'll check two things"
    #: → two calls → "both fine" reloads as an unordered pile.
    tool_call_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Message:
    """One turn of the conversation."""

    role: Role
    #: Plain text, or a list of provider-portable content blocks for
    #: multimodal turns. Runtime code that needs prose reads :attr:`text`.
    content: str | list[dict[str, Any]] = ""
    name: str | None = None
    #: Calls this assistant turn requested. First-class, not metadata.
    tool_calls: list[ToolCall] = field(default_factory=list)
    #: For ``role="tool"``: which call this answers.
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize legacy v1 pairing metadata into the typed v2 fields."""
        if not self.tool_calls:
            raw_calls = self.metadata.get("tool_calls") or []
            if isinstance(raw_calls, (list, tuple)):
                self.tool_calls = [
                    ToolCall.from_dict(entry, index=index)
                    for index, entry in enumerate(raw_calls)
                    if isinstance(entry, dict)
                ]
        else:
            for call in self.tool_calls:
                call.ensure_id()
        if self.tool_calls:
            self.metadata.setdefault(
                "tool_calls", [call.to_dict() for call in self.tool_calls]
            )
        if not self.tool_call_id:
            legacy_id = self.metadata.get("tool_call_id")
            if legacy_id:
                self.tool_call_id = str(legacy_id)
        if self.tool_call_id:
            self.metadata.setdefault("tool_call_id", self.tool_call_id)

    @property
    def text(self) -> str:
        """The textual portion of the content, whatever its shape."""
        if isinstance(self.content, str):
            return self.content
        return "\n".join(
            str(block.get("text", ""))
            for block in self.content
            if isinstance(block, dict) and block.get("type") == "text"
        )

    def to_dict(self) -> dict[str, Any]:
        # Ids are mirrored into metadata so adapters written against the older
        # shape keep working for one release. Read the field; write both.
        metadata = dict(self.metadata)
        if self.tool_calls:
            metadata["tool_calls"] = [c.to_dict() for c in self.tool_calls]
        if self.tool_call_id:
            metadata["tool_call_id"] = self.tool_call_id
        return {
            "role": self.role,
            "content": self.content,
            "name": self.name,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "metadata": metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Rebuild a message, accepting both the new and the legacy shape."""
        metadata = dict(data.get("metadata") or {})
        raw_calls = data.get("tool_calls") or metadata.get("tool_calls") or []
        calls = [
            ToolCall.from_dict(entry, index=index)
            for index, entry in enumerate(raw_calls)
            if isinstance(entry, dict)
        ]
        metadata.pop("tool_calls", None)
        call_id = data.get("tool_call_id") or metadata.pop("tool_call_id", None)
        restored = cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            name=data.get("name"),
            tool_calls=calls,
            tool_call_id=str(call_id) if call_id else None,
            metadata=metadata,
        )
        # ``__post_init__`` mirrors typed fields for directly-constructed v1
        # consumers. A deserialized v2 object is canonical, so keep its
        # metadata clean as promised by this migration boundary.
        restored.metadata.pop("tool_calls", None)
        restored.metadata.pop("tool_call_id", None)
        return restored

    @classmethod
    def from_tool_result(cls, result: ToolResult) -> "Message":
        """The ``role="tool"`` turn that answers a call, correctly paired."""
        return cls(
            role="tool",
            content=result.output,
            name=result.name,
            tool_call_id=result.tool_call_id,
            metadata={"is_error": result.is_error, "truncated": result.truncated},
        )


def pair_calls_and_results(messages: Iterable[Message]) -> tuple[bool, list[str]]:
    """Check that every tool call in *messages* has exactly one result.

    Returns ``(ok, problems)``. This is the invariant that ``modify_params``
    used to paper over by rewriting the request; asserting it directly is how
    the rewriting stays switched off.
    """
    expected: dict[str, str] = {}
    answered: set[str] = set()
    problems: list[str] = []

    for message in messages:
        for call in message.tool_calls:
            if not call.id:
                problems.append(f"tool call {call.name!r} has no id")
            elif call.id in expected:
                problems.append(f"duplicate tool call id {call.id}")
            else:
                expected[call.id] = call.name
        if message.role == "tool":
            if not message.tool_call_id:
                problems.append(f"tool result {message.name!r} has no tool_call_id")
            elif message.tool_call_id in answered:
                problems.append(f"duplicate result for {message.tool_call_id}")
            else:
                answered.add(message.tool_call_id)

    for call_id, name in expected.items():
        if call_id not in answered:
            problems.append(f"unanswered tool call {name!r} ({call_id})")
    for call_id in answered - set(expected):
        problems.append(f"result for unknown call id {call_id}")

    return (not problems), problems


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
    def steps(self) -> list[AgentEvent]:
        return self.events

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
