from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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


class Tool(Protocol):
    name: str
    description: str
    prompt_instructions: str

    def schema(self) -> dict[str, Any]: ...

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput: ...
