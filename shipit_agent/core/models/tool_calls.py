"""A tool call, which carries its own id, and the result it produced."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from typing import Any

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
