"""Stable gateway for tools hidden by progressive discovery."""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


TOOL_INVOKER_STATE_KEY = "progressive_tool_invoker"

CALL_TOOL_PROMPT = """
Use `call_tool` only for a capability that is hidden behind progressive tool
discovery. First use `tool_search` with `detail="schema"` to learn the exact
tool name and arguments. Then pass that name and arguments here.

Do not use this gateway for a directly available tool. For workflows that
need loops, filtering, or several hidden resources, prefer `execute_code`.
""".strip()


class CallToolTool:
    """Invoke one hidden tool through the runtime's normal security path."""

    # The gateway itself changes nothing. The delegated tool is authorized
    # independently by the runtime using its real contract.
    read_only = True

    def __init__(self, *, name: str = "call_tool") -> None:
        self.name = name
        self.description = (
            "Call one tool found by tool_search without loading every tool "
            "schema into the model context."
        )
        self.prompt = CALL_TOOL_PROMPT
        self.prompt_instructions = CALL_TOOL_PROMPT

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact tool name returned by tool_search.",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments matching that tool's schema.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        invoker = context.state.get(TOOL_INVOKER_STATE_KEY)
        if invoker is None:
            return ToolOutput(
                text="Progressive tool discovery is not enabled for this run.",
                metadata={"error": "progressive_discovery_disabled"},
            )

        requested = str(kwargs.get("name") or "").strip()
        arguments = kwargs.get("arguments")
        if not requested:
            return ToolOutput(
                text="call_tool requires the exact tool `name`.",
                metadata={"error": "missing_tool_name"},
            )
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                arguments = parsed
        if not isinstance(arguments, dict):
            return ToolOutput(
                text=(
                    "call_tool `arguments` must be a JSON object mapping "
                    "argument names to values. Use tool_search with "
                    "detail=\"schema\" for the selected tool, then retry."
                ),
                metadata={"error": "invalid_tool_arguments", "tool": requested},
            )

        try:
            output, metadata = invoker(requested, dict(arguments))
        except (KeyError, PermissionError, ValueError) as exc:
            return ToolOutput(
                text=f"Could not call hidden tool '{requested}': {exc}",
                metadata={"error": str(exc), "tool": requested},
            )
        return ToolOutput(
            text=output,
            metadata={
                **dict(metadata),
                "delegated_tool": requested,
                "progressive_discovery": True,
            },
        )
