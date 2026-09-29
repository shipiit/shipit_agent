from __future__ import annotations

from dataclasses import dataclass, field
import json
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

    @classmethod
    def from_records(
        cls, records: list[dict[str, Any]], *, fields: Iterable[str] | None = None,
        offset: int = 0, limit: int = 20, source: str | None = None,
    ) -> "ToolOutput":
        """Keep complete JSON while exposing an explicit paged projection.

        The tool chooses relevant records/fields; this helper never guesses
        relevance or summarizes evidence. It is not a security redaction API:
        callers and traces retain every canonical field.
        """
        if offset < 0 or limit < 1:
            raise ValueError("offset must be >= 0 and limit must be >= 1")
        columns = list(fields) if fields is not None else None
        page = records[offset:offset + limit]
        rows = [{key: row[key] for key in columns if key in row} for row in page] if columns is not None else page
        next_offset = offset + len(page) if offset + len(page) < len(records) else None
        view = {"records": rows, "total_records": len(records), "offset": offset,
                "returned_records": len(rows), "next_offset": next_offset}
        if columns is not None:
            view["selected_fields"] = columns
        if source is not None:
            view["source"] = source
        return cls(
            text=json.dumps(records, ensure_ascii=False),
            model_text=json.dumps(view, ensure_ascii=False),
            metadata={"projection": {"total_records": len(records), "offset": offset,
                                     "returned_records": len(rows), "next_offset": next_offset}},
        )


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
