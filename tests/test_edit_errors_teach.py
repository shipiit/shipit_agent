"""Edit errors say exactly what to fix.

The commonest way an exact-match edit fails is copying read_file's line
numbers ("  12: code") into old_text. The error now names that cause.
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file.edit_file_tool import EditFileTool
from shipit_agent.tools.edit_file.multi_edit_tool import MultiEditTool
from shipit_agent.tools.file_state import record_file_seen


def _seen(tmp_path: Path) -> tuple[Path, ToolContext]:
    path = tmp_path / "app.py"
    path.write_text("def greet():\n    return 'hi'\n")
    context = ToolContext(
        prompt="t", state={"read_files": set(), "read_file_mtimes": {}}
    )
    record_file_seen(context.state, path)
    return path, context


def test_line_number_prefixes_are_named_as_the_cause(tmp_path: Path) -> None:
    path, context = _seen(tmp_path)
    out = EditFileTool(root_dir=tmp_path).run(
        context,
        path="app.py",
        old_text="     2:     return 'hi'",
        new_text="    return 'yo'",
    )
    assert out.metadata["error"] == "old_text_not_found"
    assert "line-number" in out.text


def test_a_plain_miss_does_not_blame_line_numbers(tmp_path: Path) -> None:
    path, context = _seen(tmp_path)
    out = EditFileTool(root_dir=tmp_path).run(
        context, path="app.py", old_text="return 'hello'", new_text="x"
    )
    assert out.metadata["error"] == "old_text_not_found"
    assert "line-number" not in out.text


def test_multi_edit_names_line_number_prefixes_too(tmp_path: Path) -> None:
    path, context = _seen(tmp_path)
    out = MultiEditTool(root_dir=tmp_path).run(
        context,
        path="app.py",
        edits=[{"old_text": "1: def greet():", "new_text": "def hi():"}],
    )
    assert out.metadata.get("is_error")
    assert "line-number" in out.text
