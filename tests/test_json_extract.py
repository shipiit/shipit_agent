"""Regression tests for JSONParser._extract_json (PARSE-1)."""

from __future__ import annotations

import pytest

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser


class TestExtractBraceScan:
    def test_trailing_prose_with_stray_brace(self):
        # rfind('}') used to grab the stray trailing brace and blow up.
        parser = JSONParser()
        assert parser.parse('text {"a":1} more }') == {"a": 1}

    def test_object_with_trailing_text(self):
        parser = JSONParser()
        assert parser.parse('Here is the answer: {"x": 42, "y": "z"} thanks!') == {
            "x": 42,
            "y": "z",
        }

    def test_brace_inside_string_literal(self):
        parser = JSONParser()
        assert parser.parse('prefix {"a": "}{"} suffix') == {"a": "}{"}

    def test_escaped_quote_in_string(self):
        parser = JSONParser()
        assert parser.parse('{"a": "she said \\"hi\\""}') == {"a": 'she said "hi"'}

    def test_array(self):
        parser = JSONParser()
        assert parser.parse("see [1, 2, [3, 4]] end ]") == [1, 2, [3, 4]]

    def test_nested_object(self):
        parser = JSONParser()
        assert parser.parse('{"a": {"b": {"c": 1}}} trailing }') == {
            "a": {"b": {"c": 1}}
        }


class TestExtractFence:
    def test_prefers_json_fence_over_python_fence(self):
        text = (
            "Here is some code:\n"
            "```python\nprint('hi')\n```\n"
            "And the result:\n"
            '```json\n{"ok": true}\n```\n'
        )
        parser = JSONParser()
        assert parser.parse(text) == {"ok": True}

    def test_falls_back_to_brace_scan_when_fence_not_json(self):
        # A lone ```python block with valid JSON elsewhere in prose.
        text = "```python\nx = 1\n```\nThe data is {\"v\": 9}."
        parser = JSONParser()
        assert parser.parse(text) == {"v": 9}

    def test_plain_json_fence(self):
        parser = JSONParser()
        assert parser.parse('```json\n{"a": 1}\n```') == {"a": 1}

    def test_unlabeled_fence(self):
        parser = JSONParser()
        assert parser.parse('```\n{"a": 1}\n```') == {"a": 1}


class TestValidateTypes:
    def test_missing_required_key(self):
        parser = JSONParser(schema={"required": ["name"]})
        with pytest.raises(ParseError, match="Missing required key"):
            parser.parse('{"other": 1}')

    def test_type_check_string(self):
        schema = {"required": ["name"], "properties": {"name": {"type": "string"}}}
        parser = JSONParser(schema=schema)
        assert parser.parse('{"name": "ok"}') == {"name": "ok"}
        with pytest.raises(ParseError, match="type"):
            parser.parse('{"name": 5}')

    def test_type_check_integer_rejects_bool(self):
        schema = {"properties": {"n": {"type": "integer"}}}
        parser = JSONParser(schema=schema)
        assert parser.parse('{"n": 3}') == {"n": 3}
        with pytest.raises(ParseError, match="type"):
            parser.parse('{"n": true}')

    def test_type_check_array_and_object(self):
        schema = {
            "properties": {"items": {"type": "array"}, "meta": {"type": "object"}}
        }
        parser = JSONParser(schema=schema)
        assert parser.parse('{"items": [1], "meta": {}}') == {
            "items": [1],
            "meta": {},
        }
        with pytest.raises(ParseError, match="type"):
            parser.parse('{"items": "no"}')

    def test_type_check_number_allows_int_and_float(self):
        schema = {"properties": {"x": {"type": "number"}}}
        parser = JSONParser(schema=schema)
        assert parser.parse('{"x": 1}') == {"x": 1}
        assert parser.parse('{"x": 1.5}') == {"x": 1.5}
