from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MarkdownResult:
    """Parsed sections from markdown text."""

    code_blocks: list[dict[str, str]] = field(default_factory=list)
    headings: list[dict[str, str]] = field(default_factory=list)
    lists: list[str] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_blocks": self.code_blocks,
            "headings": [h for h in self.headings],
            "lists": self.lists,
        }


class MarkdownParser:
    """Parse structured content from markdown-formatted LLM output.

    Extracts code blocks, headings, and list items.

    Example::

        parser = MarkdownParser()
        result = parser.parse("# Title\\n```python\\nprint('hi')\\n```\\n- item 1")
        result.code_blocks  # [{"language": "python", "code": "print('hi')"}]
        result.headings     # [{"level": 1, "text": "Title"}]
        result.lists        # ["item 1"]
    """

    def parse(self, text: str) -> MarkdownResult:
        result = MarkdownResult(raw=text)
        result.code_blocks = self._extract_code_blocks(text)
        result.headings = self._extract_headings(text)
        result.lists = self._extract_lists(text)
        return result

    def get_format_instructions(self) -> str:
        return "Respond in Markdown format with headings, code blocks, and lists as needed."

    @staticmethod
    def _extract_code_blocks(text: str) -> list[dict[str, str]]:
        blocks = []
        for match in re.finditer(r"```(\w*)\s*\n(.*?)\n\s*```", text, re.DOTALL):
            blocks.append({
                "language": match.group(1) or "text",
                "code": match.group(2).strip(),
            })
        return blocks

    @staticmethod
    def _extract_headings(text: str) -> list[dict[str, str]]:
        headings = []
        for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
            headings.append({
                "level": str(len(match.group(1))),
                "text": match.group(2).strip(),
            })
        return headings

    @staticmethod
    def _extract_lists(text: str) -> list[str]:
        items = []
        for match in re.finditer(r"^\s*[-*+]\s+(.+)$", text, re.MULTILINE):
            items.append(match.group(1).strip())
        return items
