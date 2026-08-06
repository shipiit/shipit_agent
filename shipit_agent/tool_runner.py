from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.models import ToolCall, ToolResult
from shipit_agent.registry import ToolRegistry
from shipit_agent.tools import ToolContext


def _declared_parameters(tool: Any) -> tuple[set[str], list[str]]:
    """``(all parameter names, required names)`` from a tool's schema."""
    try:
        schema = tool.schema() or {}
        function = schema.get("function", schema)
        parameters = function.get("parameters") or {}
        return (
            set((parameters.get("properties") or {}).keys()),
            list(parameters.get("required") or []),
        )
    except Exception:
        return set(), []


def _missing_argument(
    exc: Exception, supplied: dict[str, Any], declared: set[str]
) -> str | None:
    """The argument name a KeyError/TypeError is complaining about.

    Returns ``None`` when the exception is about something else. A tool with a
    genuine bug must still surface as a failure — relabelling it as the
    model's mistake would send the model retrying a call that was fine.
    """
    if isinstance(exc, KeyError):
        key = exc.args[0] if exc.args else None
        if not isinstance(key, str) or key in supplied:
            return None
        # It must be a parameter the tool *declares*. A KeyError from a tool's
        # own internal dict lookup names something the caller was never asked
        # for, and that is a bug in the tool.
        return key if key in declared else None

    text = str(exc)
    if "required" not in text or "argument" not in text:
        return None
    match = re.search(r"argument:? \'([^\']+)\'", text)
    if match is None:
        return None
    name = match.group(1)
    return name if not declared or name in declared else None


def _missing_argument_message(name: str, missing: str, required: list[str]) -> str:
    """What the model is told, including which arguments the tool requires.

    Listing them all means the next turn can supply everything, rather than
    discovering them one at a time over three round trips.
    """
    detail = f" Required: {', '.join(required)}." if required else ""
    return (
        f"Error: {name} needs the '{missing}' argument, which was not "
        f"provided.{detail} Call it again with that argument."
    )


@dataclass(slots=True)
class ToolRunnerResult:
    results: list[ToolResult] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)


class ToolRunner:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # Argument names reserved by the runtime's tool-calling convention.
    # If the LLM happens to emit any of these as tool arguments (observed with
    # `gpt-oss-120b` and a few other models that hallucinate a `context` or
    # `self` key), they would collide with Python's positional parameter and
    # raise `TypeError: run() got multiple values for argument 'context'`.
    # We strip them before forwarding so the tool receives only real args.
    _RESERVED_ARG_NAMES: frozenset[str] = frozenset({"context", "self"})

    def run_tool_call(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self.registry.get(tool_call.name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_call.name}")

        # Filter out reserved argument names that would collide with the
        # positional `context` parameter passed by the runner.
        safe_arguments = {
            k: v
            for k, v in tool_call.arguments.items()
            if k not in self._RESERVED_ARG_NAMES
        }
        try:
            output = tool.run(context, **safe_arguments)
        except (KeyError, TypeError) as exc:
            # A tool that reads `kwargs["path"]` raises KeyError when the
            # model omits it, and one with a typed signature raises TypeError.
            # Both surface as a crash the model cannot act on — and the retry
            # policy then retries an identical call that fails identically.
            #
            # Models omit arguments constantly; that is why tool_healing
            # exists. Turn it into a result that names what is missing, so the
            # next turn can supply it.
            declared, required = _declared_parameters(tool)
            missing = _missing_argument(exc, safe_arguments, declared)
            if missing is None:
                raise
            return ToolResult(
                name=tool_call.name,
                output=_missing_argument_message(tool_call.name, missing, required),
                metadata={"error": "missing_argument", "argument": missing},
            )
        return ToolResult(
            name=tool_call.name, output=output.text, metadata=dict(output.metadata)
        )

    def run_many(
        self, tool_calls: list[ToolCall], context: ToolContext
    ) -> ToolRunnerResult:
        result = ToolRunnerResult()
        for tool_call in tool_calls:
            tool = self.registry.get(tool_call.name)
            if tool is None:
                result.missing_tools.append(tool_call.name)
                continue
            result.results.append(self.run_tool_call(tool_call, context))
        return result
