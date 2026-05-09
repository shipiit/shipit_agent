"""Tests for the streaming-partial-JSON parser."""

from __future__ import annotations

from shipit_agent.parsers.streaming_json import parse_partial_json


class TestParsePartialJsonComplete:
    """Inputs that are already valid JSON should round-trip."""

    def test_complete_object(self) -> None:
        assert parse_partial_json('{"a": 1}') == {"a": 1}

    def test_complete_array(self) -> None:
        assert parse_partial_json("[1, 2, 3]") == [1, 2, 3]

    def test_nested(self) -> None:
        assert parse_partial_json('{"x": {"y": [1, 2]}}') == {"x": {"y": [1, 2]}}

    def test_strings_with_escapes(self) -> None:
        assert parse_partial_json('{"q": "line1\\nline2"}') == {"q": "line1\nline2"}


class TestParsePartialJsonIncomplete:
    """Common incomplete-stream cases."""

    def test_open_string(self) -> None:
        assert parse_partial_json('{"name": "Al') == {"name": "Al"}

    def test_open_object_with_complete_value(self) -> None:
        assert parse_partial_json('{"a": 1') == {"a": 1}

    def test_open_object_with_trailing_key_no_value(self) -> None:
        # Dangling `"key":` should be dropped, leaving the parsed-so-far object
        result = parse_partial_json('{"a": 1, "b":')
        assert result == {"a": 1}

    def test_open_array_with_partial_value(self) -> None:
        # `[1, 2,` → trailing comma dropped → [1, 2]
        assert parse_partial_json("[1, 2,") == [1, 2]

    def test_open_array_with_complete_values(self) -> None:
        assert parse_partial_json("[1, 2") == [1, 2]

    def test_nested_open_array(self) -> None:
        assert parse_partial_json('{"items": [1, 2, ') == {"items": [1, 2]}

    def test_open_string_inside_array(self) -> None:
        assert parse_partial_json('{"tags": ["foo", "ba') == {"tags": ["foo", "ba"]}


class TestParsePartialJsonProseAndFences:
    """Tolerate leading prose / partial code fences."""

    def test_prose_before_object(self) -> None:
        # Text starting with prose, finding a JSON structure mid-string
        result = parse_partial_json('Sure! Here you go: {"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_partial_keyword_dropped(self) -> None:
        # `tru` (incomplete keyword) — the fallback path drops it
        result = parse_partial_json('{"done": tr')
        # Should be {} (no valid value yet) or None — both are acceptable
        assert result == {} or result is None


class TestParsePartialJsonEdgeCases:
    def test_empty(self) -> None:
        assert parse_partial_json("") is None

    def test_whitespace_only(self) -> None:
        assert parse_partial_json("   \n  ") is None

    def test_no_json_structure(self) -> None:
        assert parse_partial_json("just some prose") is None

    def test_only_open_brace(self) -> None:
        assert parse_partial_json("{") == {}

    def test_only_open_bracket(self) -> None:
        assert parse_partial_json("[") == []

    def test_string_with_quotes_escaped(self) -> None:
        assert parse_partial_json('{"q": "she said \\"hi\\""}') == {"q": 'she said "hi"'}
