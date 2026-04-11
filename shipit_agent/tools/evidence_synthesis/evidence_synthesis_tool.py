from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import EVIDENCE_SYNTHESIS_PROMPT


class EvidenceSynthesisTool:
    def __init__(
        self,
        *,
        name: str = "synthesize_evidence",
        description: str = "Turn raw observations into facts, inferences, gaps, and recommendations.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or EVIDENCE_SYNTHESIS_PROMPT
        self.prompt_instructions = "Use this after search, connector, or workspace tools when several observations must be distilled."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "observations": {
                            "type": "array",
                            "description": "Facts, excerpts, or observations to synthesize",
                        },
                        "question": {
                            "type": "string",
                            "description": "Optional framing question",
                        },
                    },
                    "required": ["observations"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        observations = [
            str(item).strip()
            for item in kwargs.get("observations", [])
            if str(item).strip()
        ]
        question = str(kwargs.get("question", "")).strip()
        facts = observations[:4]
        inferences = observations[4:6]
        lines = []
        if question:
            lines.append(f"Question: {question}")
        lines.append("Facts:")
        lines.extend(f"- {item}" for item in facts or ["No concrete facts provided."])
        lines.append("Inferences:")
        lines.extend(
            f"- {item}"
            for item in inferences
            or ["Need more evidence before drawing stronger conclusions."]
        )
        lines.append("Gaps:")
        lines.append(
            "- Confirm the missing source of truth and unresolved assumptions."
        )
        lines.append("Recommendations:")
        lines.append("- Gather the next highest-signal piece of evidence.")
        lines.append("- Verify the most important claim before acting on it.")
        return ToolOutput(
            text="\n".join(lines),
            metadata={"question": question, "observation_count": len(observations)},
        )
