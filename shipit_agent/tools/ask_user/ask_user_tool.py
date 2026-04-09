from __future__ import annotations

import json

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import ASK_USER_PROMPT


class AskUserTool:
    def __init__(
        self,
        *,
        name: str = "ask_user",
        description: str = "Request structured user input as part of a human-in-the-loop flow.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or ASK_USER_PROMPT
        self.prompt_instructions = (
            "Use this only when missing user input blocks safe progress. "
            "Ask focused questions with clear options when possible."
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
                        "question": {"type": "string", "description": "Question to ask the user"},
                        "context": {"type": "string", "description": "Optional context"},
                        "options": {"type": "array", "description": "Suggested options"},
                    },
                    "required": ["question"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        payload = {
            "kind": "ask_user",
            "question": kwargs["question"],
            "context": kwargs.get("context", ""),
            "options": kwargs.get("options", []),
        }
        return ToolOutput(text=json.dumps(payload), metadata={"interactive": True, **payload})
