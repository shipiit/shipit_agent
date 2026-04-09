from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import VERIFIER_PROMPT


class VerifierTool:
    def __init__(
        self,
        *,
        name: str = "verify_output",
        description: str = "Check whether content satisfies a set of required criteria.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or VERIFIER_PROMPT
        self.prompt_instructions = (
            "Use this to validate outputs against explicit criteria before returning or publishing them."
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
                        "content": {"type": "string", "description": "Content to verify"},
                        "criteria": {"type": "array", "description": "Required checks"},
                    },
                    "required": ["content", "criteria"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        content = str(kwargs["content"])
        criteria = list(kwargs.get("criteria", []))
        checks = []
        passed = True
        for criterion in criteria:
            matched = str(criterion).lower() in content.lower()
            passed = passed and matched
            checks.append({"criterion": criterion, "passed": matched})
        summary = "passed" if passed else "failed"
        lines = [f"Verification {summary}:"]
        lines.extend(f"- {item['criterion']}: {'ok' if item['passed'] else 'missing'}" for item in checks)
        return ToolOutput(text="\n".join(lines), metadata={"passed": passed, "checks": checks})
