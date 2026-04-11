from __future__ import annotations

from dataclasses import dataclass, field

from shipit_agent.models import ToolCall, ToolResult
from shipit_agent.registry import ToolRegistry
from shipit_agent.tools import ToolContext


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
        output = tool.run(context, **safe_arguments)
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
