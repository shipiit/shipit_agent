from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import DECISION_MATRIX_PROMPT


class DecisionMatrixTool:
    def __init__(
        self,
        *,
        name: str = "decision_matrix",
        description: str = "Compare options against explicit criteria and recommend the strongest choice.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or DECISION_MATRIX_PROMPT
        self.prompt_instructions = "Use this when there are multiple valid paths and the agent should recommend one clearly."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "description": "Decision to make",
                        },
                        "options": {
                            "type": "array",
                            "description": "Candidate options",
                        },
                        "criteria": {
                            "type": "array",
                            "description": "Evaluation criteria",
                        },
                    },
                    "required": ["decision", "options", "criteria"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        decision = str(kwargs["decision"]).strip()
        options = [
            str(item).strip() for item in kwargs.get("options", []) if str(item).strip()
        ]
        criteria = [
            str(item).strip()
            for item in kwargs.get("criteria", [])
            if str(item).strip()
        ]
        recommendation = options[0] if options else "No option provided"
        fallback = options[1] if len(options) > 1 else recommendation
        lines = [f"Decision: {decision}", "Comparison Matrix:"]
        for option in options:
            criteria_summary = (
                ", ".join(criteria) if criteria else "No criteria provided"
            )
            lines.append(f"- {option}: evaluate against {criteria_summary}")
        lines.append(f"Recommendation: {recommendation}")
        lines.append(f"Fallback: {fallback}")
        lines.append("Tradeoffs:")
        lines.append(
            "- Favor the option with the strongest fit to the highest-priority criteria."
        )
        lines.append("- Keep a fallback when execution risk is high.")
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "decision": decision,
                "options": options,
                "criteria": criteria,
                "recommendation": recommendation,
                "fallback": fallback,
            },
        )
