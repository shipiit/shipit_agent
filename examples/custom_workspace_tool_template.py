from __future__ import annotations

from typing import Any

from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.tools.base import ToolContext, ToolOutput


class WorkspaceConventionTool:
    name = "workspace_conventions"
    description = "Return local workspace conventions and delivery rules."
    prompt = "Use this when local project conventions matter for the final answer."
    prompt_instructions = "Prefer this over guessing team-specific conventions."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Convention area to explain",
                        },
                    },
                    "required": ["topic"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        topic = str(kwargs.get("topic", "")).strip()
        return ToolOutput(
            text=f"Workspace convention for '{topic}': be explicit, verify the result, and keep outputs reproducible.",
            metadata={"topic": topic},
        )


agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[WorkspaceConventionTool()],
)

if __name__ == "__main__":
    result = agent.run("What are the workspace conventions?")
    print(result.output)
