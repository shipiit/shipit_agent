from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import THOUGHT_DECOMPOSITION_PROMPT


class ThoughtDecompositionTool:
    def __init__(
        self,
        *,
        name: str = "decompose_problem",
        description: str = "Break a problem into workstreams, assumptions, risks, evidence needs, and next actions.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or THOUGHT_DECOMPOSITION_PROMPT
        self.prompt_instructions = (
            "Use this when the task needs visible structured reasoning before execution."
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
                        "problem": {"type": "string", "description": "Problem or task to break down"},
                        "objective": {"type": "string", "description": "Desired outcome"},
                        "constraints": {"type": "array", "description": "Known limits or requirements"},
                    },
                    "required": ["problem"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        problem = str(kwargs["problem"]).strip()
        objective = str(kwargs.get("objective", "")).strip()
        constraints = [str(item).strip() for item in kwargs.get("constraints", []) if str(item).strip()]
        lines = [f"Problem: {problem}"]
        if objective:
            lines.append(f"Objective: {objective}")
        lines.extend(
            [
                "Workstreams:",
                "1. Clarify scope and target outcome.",
                "2. Gather missing evidence and dependencies.",
                "3. Execute the highest-value actions first.",
                "4. Verify the result against constraints and risks.",
                "Assumptions:",
                "- The available tools and data are sufficient to make progress.",
                "- The task can be advanced through observable intermediate outputs.",
                "Risks:",
                "- Missing credentials, context, or external dependencies can block execution.",
                "- Ambiguous requirements can create wasted work.",
                "Evidence Needed:",
                "- Confirm the source of truth for important decisions.",
                "- Check current workspace state before making irreversible changes.",
                "Next Actions:",
                "- Pick the first evidence-gathering step.",
                "- Execute one verifiable task.",
                "- Reassess after each meaningful result.",
            ]
        )
        if constraints:
            lines.append("Constraints:")
            lines.extend(f"- {constraint}" for constraint in constraints)
        return ToolOutput(
            text="\n".join(lines),
            metadata={"problem": problem, "objective": objective, "constraints": constraints},
        )
