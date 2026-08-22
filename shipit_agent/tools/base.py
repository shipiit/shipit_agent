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
    """A complete tool result plus an optional compact model-facing view.

    ``text`` is always the canonical result retained for callers and traces.
    A tool that understands its result shape may provide ``model_text`` with
    the relevant rows, fields, or snippets. The runtime then sends that view
    to the model instead of blindly taking characters from the canonical
    payload. This is an explicit tool contract, not tool-name-specific logic.
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    model_text: str | None = None


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
