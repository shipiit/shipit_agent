from __future__ import annotations

import json

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import HUMAN_REVIEW_PROMPT


class HumanReviewTool:
    def __init__(
        self,
        *,
        name: str = "human_review",
        description: str = "Pause for human review and approval before continuing.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or HUMAN_REVIEW_PROMPT
        self.prompt_instructions = (
            "Use this before high-impact actions or when a proposed change should be approved by a human."
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
                        "summary": {"type": "string", "description": "What requires review"},
                        "preview": {"type": "string", "description": "Preview of the proposed action"},
                    },
                    "required": ["summary"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        payload = {
            "kind": "human_review",
            "summary": kwargs["summary"],
            "preview": kwargs.get("preview", ""),
        }
        return ToolOutput(text=json.dumps(payload), metadata={"interactive": True, **payload})
