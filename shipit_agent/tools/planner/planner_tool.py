from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import PLANNER_PROMPT


class PlannerTool:
    def __init__(
        self,
        *,
        name: str = "plan_task",
        description: str = "Generate a concrete execution plan with ordered steps, risks, and checkpoints.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or PLANNER_PROMPT
        self.prompt_instructions = (
            "Use this before larger workflows or when a task benefits from decomposition into clear steps."
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
                        "goal": {"type": "string", "description": "Desired end state"},
                        "constraints": {"type": "array", "description": "Optional constraints"},
                    },
                    "required": ["goal"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        goal = str(kwargs["goal"]).strip()
        constraints = list(kwargs.get("constraints", []))
        lines = [
            f"Goal: {goal}",
            "Plan:",
            "1. Clarify the target output and inputs.",
            "2. Select the right tools and gather evidence.",
            "3. Execute the task in small verifiable steps.",
            "4. Verify the result against constraints.",
            "5. Return the final deliverable and note any residual risks.",
        ]
        if constraints:
            lines.append("Constraints:")
            lines.extend(f"- {constraint}" for constraint in constraints)
        return ToolOutput(text="\n".join(lines), metadata={"goal": goal, "constraints": constraints})
