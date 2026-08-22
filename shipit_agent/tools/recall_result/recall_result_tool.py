"""On-demand access to large results omitted from active chat history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shipit_agent.tools.base import ToolOutput


@dataclass(frozen=True, slots=True)
class RecallableResult:
    call_id: str
    name: str
    output: str
    metadata: Mapping[str, Any]


class RecallToolResult:
    """Read a bounded slice of an earlier tool result by its stable call id.

    The complete result remains in the session store; ordinary prompts carry a
    short pointer. This tool pays for old evidence only when a later question
    genuinely needs it.
    """

    name = "recall_tool_result"
    description = (
        "Recall an exact bounded slice of a large tool result from an earlier "
        "turn using the call_id shown in conversation history."
    )
    prompt_instructions = (
        "Use only when the prior assistant answer is insufficient and exact "
        "older evidence is needed. Do not recall results speculatively."
    )
    read_only = True

    def __init__(self, results: Mapping[str, RecallableResult]) -> None:
        self._results = dict(results)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "call_id": {
                            "type": "string",
                            "description": "Stable id of the earlier tool call.",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 0,
                            "default": 0,
                            "description": "Character offset into the result.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 256,
                            "maximum": 20000,
                            "default": 8000,
                            "description": "Maximum characters to return.",
                        },
                    },
                    "required": ["call_id"],
                    "additionalProperties": False,
                },
            },
        }

    def run(
        self,
        context: Any,
        *,
        call_id: str,
        offset: int = 0,
        limit: int = 8000,
        **_: Any,
    ) -> ToolOutput:
        record = self._results.get(str(call_id))
        if record is None:
            available = ", ".join(sorted(self._results)[:20]) or "none"
            return ToolOutput(
                text=(
                    f"No recallable result exists for call_id={call_id!r}. "
                    f"Available call ids: {available}."
                ),
                metadata={"is_error": True, "call_id": call_id},
            )
        start = max(0, int(offset or 0))
        size = min(20_000, max(256, int(limit or 8000)))
        end = min(len(record.output), start + size)
        excerpt = record.output[start:end]
        more = end < len(record.output)
        header = (
            f"[recalled {record.name} call_id={record.call_id}; "
            f"chars {start}:{end} of {len(record.output)}"
            + (f"; continue with offset={end}" if more else "; complete")
            + "]\n"
        )
        return ToolOutput(
            text=header + excerpt,
            metadata={
                "recalled": True,
                "source_call_id": record.call_id,
                "source_tool": record.name,
                "offset": start,
                "next_offset": end if more else None,
                "total_chars": len(record.output),
            },
        )


def recallable_results(
    messages: list[Any], *, min_chars: int
) -> dict[str, RecallableResult]:
    """Index large, completed historical results without copying their text."""
    found: dict[str, RecallableResult] = {}
    for message in messages:
        output = getattr(message, "content", None)
        call_id = str(
            getattr(message, "tool_call_id", None)
            or (getattr(message, "metadata", None) or {}).get("tool_call_id")
            or ""
        )
        if (
            getattr(message, "role", "") != "tool"
            or not call_id
            or not isinstance(output, str)
            or len(output) < min_chars
        ):
            continue
        found[call_id] = RecallableResult(
            call_id=call_id,
            name=str(getattr(message, "name", "") or "tool"),
            output=output,
            metadata=dict(getattr(message, "metadata", None) or {}),
        )
    return found


__all__ = ["RecallToolResult", "RecallableResult", "recallable_results"]
