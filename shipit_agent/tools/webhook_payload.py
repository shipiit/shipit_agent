from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .base import ToolContext, ToolOutput


@dataclass(slots=True)
class WebhookPayloadTool:
    """Expose the triggering webhook payload to the agent."""

    payload: dict[str, Any] = field(default_factory=dict)
    name: str = "webhook_payload"
    description: str = (
        "Access the webhook payload that triggered this agent run. "
        "Pass a dot-separated path to fetch a nested value."
    )
    prompt_instructions: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Dot-separated path to a nested payload value. "
                                "Leave empty to return the full payload."
                            ),
                        }
                    },
                },
            },
        }

    def run(self, context: ToolContext, path: str = "") -> ToolOutput:
        del context
        if not path:
            return ToolOutput(text=json.dumps(self.payload, indent=2))

        value: Any = self.payload
        for key in path.split("."):
            if isinstance(value, dict):
                if key not in value:
                    return ToolOutput(text=f"Path '{path}' not found in payload")
                value = value[key]
                continue
            if isinstance(value, list) and key.isdigit():
                index = int(key)
                if index >= len(value):
                    return ToolOutput(text=f"Path '{path}' not found in payload")
                value = value[index]
                continue
            return ToolOutput(text=f"Path '{path}' not found in payload")

        if isinstance(value, (dict, list)):
            return ToolOutput(text=json.dumps(value, indent=2))
        return ToolOutput(text=str(value))
