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

    def run_tool_call(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self.registry.get(tool_call.name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_call.name}")
        output = tool.run(context, **tool_call.arguments)
        return ToolResult(name=tool_call.name, output=output.text, metadata=dict(output.metadata))

    def run_many(self, tool_calls: list[ToolCall], context: ToolContext) -> ToolRunnerResult:
        result = ToolRunnerResult()
        for tool_call in tool_calls:
            tool = self.registry.get(tool_call.name)
            if tool is None:
                result.missing_tools.append(tool_call.name)
                continue
            result.results.append(self.run_tool_call(tool_call, context))
        return result
