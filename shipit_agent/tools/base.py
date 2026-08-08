from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import Any, Protocol, TypeAlias


@dataclass(slots=True)
class ToolContext:
    prompt: str
    system_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None


@dataclass(slots=True)
class ToolOutput:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolOutputChunk:
    """One incremental piece of a streaming tool result.

    The runner concatenates chunk text into the canonical ``ToolResult`` and
    merges metadata in arrival order. Runtimes may publish each piece live.
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


ToolRunOutput: TypeAlias = ToolOutput | Iterable[ToolOutputChunk | ToolOutput | str]


class Tool(Protocol):
    name: str
    description: str
    prompt_instructions: str

    def schema(self) -> dict[str, Any]: ...

    def run(self, context: ToolContext, **kwargs: Any) -> ToolRunOutput: ...
