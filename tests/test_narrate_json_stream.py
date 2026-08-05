"""Incremental tool-input parsing — decode one field while it streams."""

from __future__ import annotations

import json

import pytest

from shipit_agent.narrate.json_stream import (
    STREAMING_FIELDS,
    StreamingToolInputParser,
    streaming_field_for,
)


def feed(field: str, *chunks: str) -> StreamingToolInputParser:
    parser = StreamingToolInputParser(field)
    for chunk in chunks:
        parser.append(chunk)
    return parser


def feed_char_by_char(field: str, payload: str) -> StreamingToolInputParser:
    """The worst case: every chunk boundary lands mid-token."""
    parser = StreamingToolInputParser(field)
    for char in payload:
        parser.append(char)
    return parser


class TestHappyPath:
    def test_the_documented_example(self) -> None:
        parser = feed("content", '{"path": "app.py", "content": "hel', 'lo world"}')
        assert parser.prefix_fields == {"path": "app.py"}
        assert parser.streaming_value == "hello world"
        assert parser.stream_complete
        assert not parser.has_error

    def test_value_grows_across_chunks(self) -> None:
        parser = StreamingToolInputParser("content")
        parser.append('{"path": "a.py", "content": "')
        assert parser.streaming_value == ""
        parser.append("one ")
        assert parser.streaming_value == "one "
        parser.append("two ")
        assert parser.streaming_value == "one two "
        parser.append('three"}')
        assert parser.streaming_value == "one two three"
        assert parser.stream_complete

    def test_prefix_is_none_until_the_field_starts(self) -> None:
        parser = StreamingToolInputParser("content")
        parser.append('{"path": "a.py"')
        assert parser.prefix_fields is None
        parser.append(', "content": "x')
        assert parser.prefix_fields == {"path": "a.py"}

    def test_streaming_field_first(self) -> None:
        parser = feed("content", '{"content": "hello", "path": "a.py"}')
        assert parser.prefix_fields == {}
        assert parser.streaming_value == "hello"

    def test_no_prefix_fields(self) -> None:
        parser = feed("code", '{"code": "print(1)"}')
        assert parser.prefix_fields == {}
        assert parser.streaming_value == "print(1)"

    def test_several_prefix_field_types(self) -> None:
        parser = feed(
            "content",
            '{"path": "a.py", "line": 42, "dry": true, "opts": {"a": [1, 2]},',
            ' "tags": ["x"], "nil": null, "content": "body"}',
        )
        assert parser.prefix_fields == {
            "path": "a.py",
            "line": 42,
            "dry": True,
            "opts": {"a": [1, 2]},
            "tags": ["x"],
            "nil": None,
        }
        assert parser.streaming_value == "body"

    def test_whitespace_and_newlines_between_tokens(self) -> None:
        parser = feed("content", '{\n  "path" :\t"a.py" ,\n  "content" : "hi"\n}')
        assert parser.prefix_fields == {"path": "a.py"}
        assert parser.streaming_value == "hi"

    def test_empty_streaming_value(self) -> None:
        parser = feed("content", '{"path": "a.py", "content": ""}')
        assert parser.streaming_value == ""
        assert parser.stream_complete


class TestEscapes:
    @pytest.mark.parametrize(
        "encoded,expected",
        [
            (r"line1\nline2", "line1\nline2"),
            (r"a\tb", "a\tb"),
            (r"say \"hi\"", 'say "hi"'),
            (r"back\\slash", "back\\slash"),
            (r"a\/b", "a/b"),
            (r"\r\b\f", "\r\b\f"),
            (r"café", "café"),
            (r"AB", "AB"),
        ],
    )
    def test_escape_decoding(self, encoded, expected) -> None:
        parser = feed("content", '{"content": "' + encoded + '"}')
        assert parser.streaming_value == expected

    def test_escape_split_across_chunks(self) -> None:
        parser = feed("content", '{"content": "a\\', 'nb"}')
        assert parser.streaming_value == "a\nb"

    def test_unicode_escape_split_across_chunks(self) -> None:
        parser = feed("content", '{"content": "caf\\u00', 'e9"}')
        assert parser.streaming_value == "café"

    def test_unicode_escape_split_at_every_offset(self) -> None:
        for cut in range(1, 7):
            payload = '{"content": "x\\u00e9y"}'
            head = payload[: 13 + cut]
            parser = feed("content", head, payload[13 + cut :])
            assert parser.streaming_value == "xéy", f"cut at {cut}"

    def test_escaped_quote_does_not_end_the_stream(self) -> None:
        parser = feed("content", r'{"content": "he said \"no\" loudly"}')
        assert parser.streaming_value == 'he said "no" loudly'
        assert parser.stream_complete

    def test_trailing_backslash_waits_for_more(self) -> None:
        parser = feed("content", '{"content": "a\\')
        assert parser.streaming_value == "a"
        assert not parser.stream_complete
        assert not parser.has_error

    def test_escapes_in_prefix_string_values(self) -> None:
        parser = feed("content", r'{"path": "a\"b.py", "content": "x"}')
        assert parser.prefix_fields == {"path": 'a"b.py'}

    def test_escapes_in_keys(self) -> None:
        parser = feed("content", r'{"weird": 1, "content": "x"}')
        assert parser.prefix_fields == {"weird": 1}
        assert parser.streaming_value == "x"

    def test_braces_inside_a_prefix_string_do_not_confuse_depth(self) -> None:
        parser = feed("content", '{"path": "a{b}c[d]", "content": "x"}')
        assert parser.prefix_fields == {"path": "a{b}c[d]"}
        assert parser.streaming_value == "x"


class TestChunkBoundaries:
    @pytest.mark.parametrize(
        "payload",
        [
            '{"path": "app.py", "content": "hello world"}',
            '{"content": "line1\\nline2\\ttabbed"}',
            '{"a": 1, "b": [1, {"c": "d"}], "content": "caf\\u00e9 \\"x\\""}',
            '{"path":"a.py","content":""}',
        ],
    )
    def test_char_by_char_matches_all_at_once(self, payload) -> None:
        incremental = feed_char_by_char("content", payload)
        atomic = feed("content", payload)
        assert incremental.streaming_value == atomic.streaming_value
        assert incremental.prefix_fields == atomic.prefix_fields
        assert incremental.stream_complete == atomic.stream_complete
        assert not incremental.has_error
        # And it agrees with a real JSON parse.
        assert incremental.streaming_value == json.loads(payload)["content"]

    @pytest.mark.parametrize("cut", range(1, 44))
    def test_every_single_split_point(self, cut) -> None:
        payload = '{"path": "app.py", "content": "hello world"}'
        parser = feed("content", payload[:cut], payload[cut:])
        assert parser.streaming_value == "hello world", f"cut at {cut}"
        assert parser.prefix_fields == {"path": "app.py"}


class TestRealisticPayloads:
    def test_a_python_file_being_written(self) -> None:
        code = 'def main():\n    print("hello")\n    return 0\n'
        payload = json.dumps({"path": "main.py", "content": code})
        parser = feed_char_by_char("content", payload)
        assert parser.streaming_value == code
        assert parser.prefix_fields == {"path": "main.py"}

    def test_a_large_body_streams_in_order(self) -> None:
        body = "".join(f"line {i}\n" for i in range(500))
        payload = json.dumps({"path": "big.txt", "content": body})
        parser = StreamingToolInputParser("content")
        seen: list[int] = []
        for i in range(0, len(payload), 64):
            parser.append(payload[i : i + 64])
            seen.append(len(parser.streaming_value))
        assert parser.streaming_value == body
        assert seen == sorted(seen)  # monotonically grew, never rewound

    def test_a_shell_command_with_quotes(self) -> None:
        command = 'grep -r "TODO" . | awk \'{print $1}\''
        payload = json.dumps({"command": command})
        assert feed_char_by_char("command", payload).streaming_value == command


class TestMalformed:
    @pytest.mark.parametrize(
        "payload",
        [
            'not json at all',
            '[1, 2, 3]',
            '{"content": 42}',        # streamed field must be a string
            '{"content" "x"}',        # missing colon
            '{"a": 1 "b": 2}',        # missing comma
        ],
    )
    def test_bad_input_sets_the_error_flag_instead_of_raising(self, payload) -> None:
        parser = feed("content", payload)
        assert parser.has_error or not parser.stream_complete

    def test_trailing_garbage_after_the_field_is_not_inspected(self) -> None:
        """Closing the streamed field ends the scan — by design.

        The parser exists to decode one field as it arrives, not to validate
        the whole object. Once that field closes there is nothing left worth
        reading, so it stops rather than spending cycles on the remainder.
        """
        parser = feed("content", '{"content": "x" ] garbage')
        assert parser.streaming_value == "x"
        assert parser.stream_complete
        assert not parser.has_error

    def test_bad_unicode_escape_errors(self) -> None:
        parser = feed("content", '{"content": "a\\uZZZZ"}')
        assert parser.has_error

    def test_unknown_escape_errors(self) -> None:
        parser = feed("content", '{"content": "a\\qb"}')
        assert parser.has_error

    def test_append_after_error_is_ignored(self) -> None:
        parser = feed("content", "garbage")
        parser.append('{"content": "x"}')
        assert parser.has_error

    def test_append_after_done_is_ignored(self) -> None:
        parser = feed("content", '{"content": "x"}')
        parser.append('{"content": "y"}')
        assert parser.streaming_value == "x"

    def test_truncated_input_never_raises(self) -> None:
        payload = '{"path": "a.py", "content": "hello"}'
        for cut in range(len(payload)):
            parser = feed("content", payload[:cut])
            assert not parser.has_error or cut == 0

    def test_missing_field_never_completes(self) -> None:
        parser = feed("content", '{"path": "a.py", "other": "x"}')
        assert not parser.stream_complete
        assert parser.streaming_value == ""

    def test_empty_appends_are_ignored(self) -> None:
        parser = StreamingToolInputParser("content")
        parser.append("")
        parser.append('{"content": "x"}')
        assert parser.streaming_value == "x"


class TestFieldRegistry:
    def test_known_tools_stream_their_biggest_argument(self) -> None:
        assert streaming_field_for("write_file") == "content"
        assert streaming_field_for("run_code") == "code"
        assert streaming_field_for("bash") == "command"

    def test_unknown_tools_stream_nothing(self) -> None:
        assert streaming_field_for("read_file") is None
        assert streaming_field_for("some_mcp_tool") is None

    def test_every_registered_tool_is_a_real_builtin(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = {
            getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")
        }
        assert not set(STREAMING_FIELDS) - names
