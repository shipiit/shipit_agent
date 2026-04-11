from __future__ import annotations

import json
import re
from typing import Any

from shipit_agent.parsers.base import ParseError


class JSONParser:
    """Parse JSON from LLM output.

    Handles common LLM quirks: markdown code fences, trailing commas,
    and leading/trailing prose around the JSON block.
    """

    def __init__(self, *, schema: dict[str, Any] | None = None) -> None:
        self.schema = schema

    def parse(self, text: str) -> Any:
        cleaned = self._extract_json(text)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ParseError(f"Invalid JSON: {exc}", raw_text=text) from exc

        if self.schema:
            self._validate(result)
        return result

    def get_format_instructions(self) -> str:
        if self.schema:
            return f"Respond with valid JSON matching this schema:\n{json.dumps(self.schema, indent=2)}"
        return "Respond with valid JSON."

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from text that may contain markdown fences or prose."""
        # Try markdown code fence first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try to find a JSON object or array
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            if start == -1:
                continue
            end = text.rfind(end_char)
            if end > start:
                return text[start : end + 1]

        return text.strip()

    def _validate(self, result: Any) -> None:
        """Basic schema validation — checks required keys and types."""
        if not isinstance(self.schema, dict):
            return
        required = self.schema.get("required", [])
        if isinstance(result, dict):
            for key in required:
                if key not in result:
                    raise ParseError(f"Missing required key: {key}")
