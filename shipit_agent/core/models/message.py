"""A message in the conversation, its content parts, and pairing calls with their results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .kinds import Role
from .tool_calls import ToolCall, ToolResult


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
