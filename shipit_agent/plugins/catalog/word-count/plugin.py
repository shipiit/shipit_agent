"""word-count plugin — a standalone tool pack.

Registers one ``word_count`` tool. Shows the tool side of a plugin: a plugin
can contribute any object the agent accepts in ``tools=`` — here a tiny,
self-contained tool implementing the standard ``name`` / ``description`` /
``schema`` / ``run`` shape.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class WordCountTool:
    name = "word_count"
    description = "Count the words (and characters) in a piece of text."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> ToolOutput:
        text = str(kwargs.get("text", ""))
        words = len(text.split())
        return ToolOutput(
            text=f"{words} words, {len(text)} characters.",
            metadata={"words": words, "characters": len(text)},
        )


def register(reg: Any) -> None:
    reg.add_tool(WordCountTool())
