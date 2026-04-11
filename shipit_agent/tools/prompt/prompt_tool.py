from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import PROMPT_TOOL_PROMPT


class PromptTool:
    def __init__(
        self,
        *,
        name: str = "build_prompt",
        description: str = "Build or refine a system prompt from goals, constraints, and style instructions.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or PROMPT_TOOL_PROMPT
        self.prompt_instructions = "Use this to generate or refine a system prompt for a downstream agent, role, or workflow."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Primary responsibility of the prompt",
                        },
                        "constraints": {
                            "type": "array",
                            "description": "Hard constraints",
                        },
                        "style": {
                            "type": "string",
                            "description": "Tone and style guidance",
                        },
                    },
                    "required": ["goal"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        goal = str(kwargs["goal"]).strip()
        constraints = kwargs.get("constraints", [])
        style = str(kwargs.get("style", "Clear, direct, and accurate.")).strip()
        lines = [f"You are responsible for: {goal}", f"Style: {style}"]
        if constraints:
            lines.append("Constraints:")
            lines.extend(f"- {constraint}" for constraint in constraints)
        return ToolOutput(
            text="\n".join(lines),
            metadata={"goal": goal, "constraints": constraints, "style": style},
        )
