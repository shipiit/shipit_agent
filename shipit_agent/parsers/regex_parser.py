from __future__ import annotations

import re
from typing import Any

from shipit_agent.parsers.base import ParseError


class RegexParser:
    """Parse LLM output using regex patterns.

    Example::

        parser = RegexParser(
            pattern=r"Score: (\\d+)/10",
            output_keys=["score"],
        )
        result = parser.parse("The movie gets a Score: 8/10")
        # {"score": "8"}
    """

    def __init__(
        self,
        *,
        pattern: str,
        output_keys: list[str] | None = None,
        flags: int = 0,
    ) -> None:
        self.pattern = pattern
        self.output_keys = output_keys or []
        self.flags = flags
        self._compiled = re.compile(pattern, flags)

    def parse(self, text: str) -> dict[str, str]:
        match = self._compiled.search(text)
        if not match:
            raise ParseError(f"Pattern not found: {self.pattern}", raw_text=text)

        groups = match.groups()
        if self.output_keys:
            if len(groups) < len(self.output_keys):
                raise ParseError(
                    f"Expected {len(self.output_keys)} groups, got {len(groups)}",
                    raw_text=text,
                )
            return {key: groups[i] for i, key in enumerate(self.output_keys)}

        # If no keys, return numbered groups
        return {str(i): g for i, g in enumerate(groups)}

    def get_format_instructions(self) -> str:
        if self.output_keys:
            return f"Include in your response: {', '.join(self.output_keys)}"
        return f"Include text matching the pattern: {self.pattern}"
