from __future__ import annotations

from shipit_agent.stores import MemoryFact
from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import MEMORY_TOOL_PROMPT


class MemoryTool:
    def __init__(
        self,
        *,
        name: str = "memory",
        description: str = "Store and retrieve structured memory facts for the current agent.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or MEMORY_TOOL_PROMPT
        self.prompt_instructions = "Use this to persist durable facts that may matter across turns, sessions, or workflows."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["store", "search"],
                            "description": "Whether to store or search memory",
                        },
                        "content": {"type": "string", "description": "Memory content"},
                        "query": {
                            "type": "string",
                            "description": "Memory search query",
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional memory category",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        memory_store = context.state.get("memory_store")
        if memory_store is None:
            return ToolOutput(text="No memory store configured.")

        action = str(kwargs["action"])
        if action == "store":
            content = str(kwargs.get("content", "")).strip()
            if not content:
                return ToolOutput(text="No memory content provided.")
            fact = MemoryFact(
                content=content, category=str(kwargs.get("category", "general"))
            )
            memory_store.add(fact)
            return ToolOutput(
                text=f"Stored memory: {content}",
                metadata={"content": content, "category": fact.category},
            )

        if action == "search":
            query = str(kwargs.get("query", "")).strip()
            results = memory_store.search(query)
            lines = [f"- {fact.content}" for fact in results]
            return ToolOutput(
                text="\n".join(lines) if lines else "No memories found.",
                metadata={"query": query, "count": len(results)},
            )

        raise ValueError(f"Unsupported memory action: {action}")
