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
        """Extract JSON from text that may contain markdown fences or prose.

        Strategy (in order):
        1. Prefer an explicit ```json fenced block.
        2. Try any other fenced block.
        3. Forward brace/bracket scan over the whole text.

        A candidate is only accepted if it actually parses as JSON; otherwise
        we fall through to the next strategy. This prevents a leading
        ```python block from masking valid JSON elsewhere in the text.
        """
        candidates: list[str] = []

        # 1. Explicit ```json fence (preferred).
        json_fence = re.search(
            r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL | re.IGNORECASE
        )
        if json_fence:
            candidates.append(json_fence.group(1).strip())

        # 2. Any fenced block (may be ```python etc. — only used if it parses).
        any_fence = re.search(r"```(?:\w+)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if any_fence:
            candidates.append(any_fence.group(1).strip())

        # 3. Forward brace/bracket scan over the whole text.
        scanned = JSONParser._scan_balanced(text)
        if scanned is not None:
            candidates.append(scanned)

        for candidate in candidates:
            try:
                json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            return candidate

        # Nothing parsed cleanly — return the first candidate (so the caller's
        # json.loads raises a useful error) or fall back to the raw text.
        if candidates:
            return candidates[0]
        return text.strip()

    @staticmethod
    def _scan_balanced(text: str) -> str | None:
        """From the first opening brace/bracket, forward-scan tracking depth.

        Respects string literals and escapes so braces inside strings don't
        affect the depth count. Returns the substring up to the matching
        close, or ``None`` if no balanced span is found.
        """
        openers = {"{": "}", "[": "]"}
        start = -1
        opener = ""
        for i, ch in enumerate(text):
            if ch in openers:
                start = i
                opener = ch
                break
        if start == -1:
            return None

        closer = openers[opener]
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _validate(self, result: Any) -> None:
        """Basic schema validation — checks required keys and JSON-Schema types.

        Validates the ``required`` key list and, for any property declaring a
        ``type`` in ``schema["properties"]``, checks the value's JSON type
        (string/integer/number/boolean/array/object).
        """
        if not isinstance(self.schema, dict):
            return
        if not isinstance(result, dict):
            return

        required = self.schema.get("required", [])
        for key in required:
            if key not in result:
                raise ParseError(f"Missing required key: {key}")

        properties = self.schema.get("properties", {})
        if not isinstance(properties, dict):
            return
        for key, spec in properties.items():
            if not isinstance(spec, dict) or "type" not in spec:
                continue
            if key not in result:
                continue
            if not self._matches_type(result[key], spec["type"]):
                raise ParseError(
                    f"Key {key!r} has wrong type: expected {spec['type']}, "
                    f"got {type(result[key]).__name__}"
                )

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        """Check a value against a JSON-Schema primitive type name."""
        if expected == "string":
            return isinstance(value, str)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "integer":
            # JSON bools are ints in Python — exclude them explicitly.
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        # Unknown type name — don't enforce.
        return True
