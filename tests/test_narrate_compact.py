"""The compact transcript: one line per tool call, a short result, the model's words."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import AgentEvent
from shipit_agent.narrate.compact import CompactRenderer, call_label, display_name, result_lines


def _render(*events: tuple[str, dict[str, Any]], **options: Any) -> str:
    out: list[str] = []
    renderer = CompactRenderer(write=out.append, color=options.pop("color", False), **options)
    for kind, payload in events:
        renderer.feed(AgentEvent(type=kind, message="", payload=payload))
    renderer.close()
    return "".join(out)


def _call(call_id: str, tool: str, **arguments: Any) -> tuple[str, dict[str, Any]]:
    return ("tool_called", {"call_id": call_id, "tool": tool, "arguments": arguments})


def _done(call_id: str, tool: str, output: str, error: str = "") -> tuple[str, dict[str, Any]]:
    return ("tool_completed", {"call_id": call_id, "tool": tool, "output": output, "error": error})


def test_a_turn_reads_like_claude_code() -> None:
    text = _render(
        ("assistant_message", {"content": "I'll check the file.", "tool_calls": [{}]}),
        _call("a", "read_file", path="src/app.py"),
        _done("a", "read_file", "\n".join(f"{i}: line" for i in range(1, 41))),
        ("assistant_message", {"content": "It defines one route."}),
        ("final_answer", {"content": "It defines one route."}),
        ("run_completed", {"output": "It defines one route.", "summary": {"usage": {"total_tokens": 1200}}}),
        model="claude-sonnet-5-5",
    )
    assert "⏺ I'll check the file." in text
    assert "⏺ Read(src/app.py)\n  ⎿  Read 40 lines" in text
    assert text.count("It defines one route.") == 1
    assert text.rstrip().endswith("1,200 tokens · claude-sonnet-5-5")


def test_streamed_text_is_not_printed_again() -> None:
    text = _render(
        ("text_delta", {"chunk": "Hel"}), ("text_delta", {"chunk": "lo"}),
        ("assistant_message", {"content": "Hello"}),
        ("final_answer", {"content": "Hello"}),
        ("run_completed", {"output": "Hello"}),
    )
    assert text.count("Hello") == 1 and "⏺ Hello" in text


def test_long_output_shows_a_few_lines_and_how_many_more() -> None:
    lines = result_lines("bash", "exit_code: 0\nstdout:\n" + "\n".join(f"file{i}" for i in range(10)))
    assert lines == ["file0", "file1", "file2", "… +7 lines"]


def test_a_failing_command_shows_its_exit_code() -> None:
    assert result_lines("bash", "exit_code: 2\nstderr:\nno such file")[:2] == ["Exit code 2", "no such file"]
    assert result_lines("bash", "exit_code: 0\n(no output)") == ["(No output)"]


def test_searches_and_edits_summarise() -> None:
    assert result_lines("grep_files", "a.py:1: x\nb.py:2: x") == ["Found 2 lines"]
    assert result_lines("glob_files", "a.py") == ["Found 1 file"]
    assert result_lines("grep_files", "No matches found.") == ["No matches found."]
    assert result_lines("edit_file", "Updated src/app.py (1 replacement)\ndiff...") == [
        "Updated src/app.py (1 replacement)"]
    assert result_lines("web_search", "") == ["(No output)"]


def test_labels_name_the_tool_and_what_it_is_about() -> None:
    assert call_label("grep_files", {"path": "src", "pattern": "TODO"}) == "Search(TODO, path: src)"
    assert call_label("bash", {"command": "pytest -q", "timeout": None}) == "Bash(pytest -q)"
    assert call_label("read_file", {"path": "x" * 200}).endswith("…)")
    assert display_name("github__get_issue") == "github - get_issue (MCP)"
    assert display_name("my_tool") == "my_tool"


def test_errors_denials_and_rejected_arguments_are_marked() -> None:
    text = _render(
        _call("a", "bash", command="make"), _done("a", "bash", "", error="make: *** No rule"),
        ("tool_denied", {"call_id": "b", "tool": "write_file", "reason": "on the deny list"}),
        ("tool_arguments_rejected", {"tool": "read_file", "arguments": {}, "reason": "path is required"}),
    )
    assert "⏺ Bash(make)\n  ⎿  Error: make: *** No rule" in text
    assert "⏺ Write()\n  ⎿  Denied: on the deny list" in text
    assert "⏺ Read()\n  ⎿  Error: path is required" in text


def test_notices_and_failures_are_one_line_each() -> None:
    text = _render(
        ("reasoning_completed", {"content": "First check the tests.\nThen..."}),
        ("context_compacted", {}),
        ("model_fallback", {"from_model": "a", "to_model": "b"}),
        ("run_failed", {"error_type": "PermissionError", "error": "bad key"}),
    )
    assert "✻ First check the tests." in text and "Then..." not in text
    assert "✻ Compacted the conversation" in text and "Switched to b after a failed" in text
    assert "⏺ Error\n  ⎿  PermissionError: bad key" in text


def test_colour_only_when_asked() -> None:
    plain = _render(_call("a", "read_file", path="x"), _done("a", "read_file", "1"))
    coloured = _render(_call("a", "read_file", path="x"), _done("a", "read_file", "1"), color=True)
    assert "\x1b[" not in plain and "\x1b[32m⏺" in coloured


def test_no_footer_when_turned_off() -> None:
    text = _render(("run_completed", {"output": "ok", "summary": {"usage": {"total_tokens": 9}}}), show_footer=False)
    assert "tokens" not in text and "⏺ ok" in text
