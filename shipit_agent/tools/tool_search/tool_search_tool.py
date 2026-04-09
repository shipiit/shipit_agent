from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import TOOL_SEARCH_PROMPT


class ToolSearchTool:
    def __init__(
        self,
        *,
        name: str = "tool_search",
        description: str = "Search the available toolset and return the most relevant tools for a task.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or TOOL_SEARCH_PROMPT
        self.prompt_instructions = (
            "Use this when many tools are available and you need to identify the right one before acting."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Tool capability query"},
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        query = str(kwargs["query"]).lower()
        tools = context.state.get("available_tools", [])
        matches = []
        for tool in tools:
            haystack = f"{tool.get('name', '')} {tool.get('description', '')} {tool.get('prompt_instructions', '')}".lower()
            if query in haystack or any(token in haystack for token in query.split()):
                matches.append(tool)
        lines = [f"- {tool['name']}: {tool['description']}" for tool in matches[:10]]
        return ToolOutput(
            text="\n".join(lines) if lines else "No matching tools found.",
            metadata={"query": query, "matches": matches[:10]},
        )
