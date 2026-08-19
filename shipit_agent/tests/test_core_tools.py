"""The seven core tools, exercised against a real filesystem.

Restored after being lost with ``test_agent.py``: those tests lived alongside the
Agent tests and went with them, which coverage caught (grep at 28%, edit_file at
36%). These run against a real temporary directory rather than a mocked one —
the contracts being tested are about what happens on disk, and a mock of the
filesystem would be testing the mock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shipit_agent.tools import Workspace, core_tools


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, Any]:
    return {t.name: t for t in core_tools(tmp_path)}


# --------------------------------------------------------------------------- #
# Workspace containment
# --------------------------------------------------------------------------- #


def test_a_path_cannot_escape_the_workspace(tools):
    output = tools["read_file"].run(path="../../etc/passwd")
    assert output.metadata.get("is_error")
    assert "outside the workspace" in output.text


def test_a_symlink_cannot_escape_either(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "work"
    root.mkdir()
    (root / "link.txt").symlink_to(outside)

    tools = {t.name: t for t in core_tools(root)}
    output = tools["read_file"].run(path="link.txt")
    # Containment is checked after resolution, so the link resolves outside and
    # is refused — checking the string first would have let this through.
    assert output.metadata.get("is_error")


def test_the_core_tools_share_one_workspace(tools):
    assert tools["read_file"].workspace is tools["edit_file"].workspace


def test_relative_paths_resolve_against_the_root(tmp_path):
    workspace = Workspace(root=tmp_path)
    assert workspace.resolve("a/b.py") == (tmp_path / "a" / "b.py")
    assert workspace.relative(tmp_path / "a" / "b.py") == "a/b.py"


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #


def test_reading_numbers_the_lines(tmp_path, tools):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    output = tools["read_file"].run(path="a.py")
    assert "1  one" in output.text
    assert output.metadata["lines"] == 3


def test_reading_a_window_reports_the_range(tmp_path, tools):
    (tmp_path / "a.py").write_text(
        "\n".join(f"line {i}" for i in range(100)), encoding="utf-8"
    )
    output = tools["read_file"].run(path="a.py", offset=10, limit=5)
    assert "10  line 9" in output.text
    assert "of 100" in output.text


def test_an_empty_file_reads_as_empty_not_as_an_error(tmp_path, tools):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    output = tools["read_file"].run(path="a.py")
    assert not output.metadata.get("is_error")
    assert "(empty file)" in output.text


def test_reading_a_directory_is_refused(tmp_path, tools):
    (tmp_path / "sub").mkdir()
    assert tools["read_file"].run(path="sub").metadata.get("is_error")


def test_invalid_bytes_do_not_break_a_read(tmp_path, tools):
    (tmp_path / "a.bin").write_bytes(b"ok \xff\xfe bad")
    output = tools["read_file"].run(path="a.bin")
    assert not output.metadata.get("is_error")


# --------------------------------------------------------------------------- #
# write_file
# --------------------------------------------------------------------------- #


def test_write_creates_a_file(tmp_path, tools):
    tools["write_file"].run(path="a.py", content="x = 1\n")
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_write_refuses_to_clobber(tmp_path, tools):
    (tmp_path / "a.py").write_text("original", encoding="utf-8")
    output = tools["write_file"].run(path="a.py", content="replacement")
    assert output.metadata.get("is_error")
    assert (tmp_path / "a.py").read_text() == "original"


def test_write_creates_parent_directories(tmp_path, tools):
    tools["write_file"].run(path="src/deep/a.py", content="x = 1\n")
    assert (tmp_path / "src/deep/a.py").read_text() == "x = 1\n"


# --------------------------------------------------------------------------- #
# edit_file — the read-before-write contract
# --------------------------------------------------------------------------- #


def test_editing_an_unread_file_is_refused(tmp_path, tools):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    output = tools["edit_file"].run(path="a.py", old_str="x = 1", new_str="x = 2")
    assert output.metadata.get("is_error")
    assert "has not been read" in output.text
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_read_then_edit_succeeds(tmp_path, tools):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    tools["read_file"].run(path="a.py")
    output = tools["edit_file"].run(path="a.py", old_str="x = 1", new_str="x = 2")
    assert not output.metadata.get("is_error")
    assert (tmp_path / "a.py").read_text() == "x = 2\n"


def test_an_external_change_invalidates_the_read(tmp_path, tools):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    tools["read_file"].run(path="a.py")
    (tmp_path / "a.py").write_text("x = 99\n", encoding="utf-8")  # someone else
    output = tools["edit_file"].run(path="a.py", old_str="x = 99", new_str="x = 2")
    assert output.metadata.get("is_error")
    assert "changed on disk" in output.text


def test_writing_then_editing_needs_no_second_read(tmp_path, tools):
    """A file this session created is a file this session has seen."""
    tools["write_file"].run(path="a.py", content="x = 1\n")
    output = tools["edit_file"].run(path="a.py", old_str="x = 1", new_str="x = 2")
    assert not output.metadata.get("is_error")


def test_a_second_edit_after_the_first_succeeds(tmp_path, tools):
    """The editor re-records after writing, or the next edit looks stale."""
    tools["write_file"].run(path="a.py", content="a\nb\n")
    tools["edit_file"].run(path="a.py", old_str="a", new_str="A")
    output = tools["edit_file"].run(path="a.py", old_str="b", new_str="B")
    assert not output.metadata.get("is_error")
    assert (tmp_path / "a.py").read_text() == "A\nB\n"


def test_an_ambiguous_edit_is_refused(tmp_path, tools):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    tools["read_file"].run(path="a.py")
    output = tools["edit_file"].run(path="a.py", old_str="x = 1", new_str="x = 2")
    assert output.metadata.get("is_error")
    assert "matched 2 times" in output.text
    assert (tmp_path / "a.py").read_text() == "x = 1\nx = 1\n"


def test_a_missed_match_shows_the_nearest_text(tmp_path, tools):
    (tmp_path / "a.py").write_text("def run(self):\n    pass\n", encoding="utf-8")
    tools["read_file"].run(path="a.py")
    output = tools["edit_file"].run(path="a.py", old_str="def run(self) :", new_str="x")
    assert "Closest text found" in output.text


def test_an_edit_reports_the_line_delta(tmp_path, tools):
    tools["write_file"].run(path="a.py", content="a\n")
    output = tools["edit_file"].run(path="a.py", old_str="a", new_str="a\nb\nc")
    assert "+2 lines" in output.text


def test_editing_a_missing_file_is_refused(tools):
    assert tools["edit_file"].run(
        path="nope.py", old_str="a", new_str="b"
    ).metadata.get("is_error")


# --------------------------------------------------------------------------- #
# bash
# --------------------------------------------------------------------------- #


def test_bash_returns_stdout(tools):
    assert "hello" in tools["bash"].run(command="echo hello").text


def test_bash_includes_stderr(tools):
    assert "oops" in tools["bash"].run(command="echo oops >&2").text


def test_bash_reports_a_non_zero_exit_rather_than_hiding_it(tools):
    output = tools["bash"].run(command="exit 3")
    assert output.metadata["exit_code"] == 3
    assert "exit status 3" in output.text


def test_bash_runs_in_the_workspace(tmp_path, tools):
    (tmp_path / "marker.txt").write_text("", encoding="utf-8")
    assert "marker.txt" in tools["bash"].run(command="ls").text


def test_bash_timeout_is_a_recoverable_result(tools):
    output = tools["bash"].run(command="sleep 5", timeout=1)
    assert output.metadata.get("is_error")
    assert "timed out" in output.text


def test_bash_output_is_bounded(tmp_path):
    tools = {t.name: t for t in core_tools(tmp_path, max_output_chars=500)}
    output = tools["bash"].run(command="python3 -c \"print('x' * 20000)\"")
    assert output.metadata["truncated"]
    assert len(output.text) < 800
    assert "characters omitted" in output.text


def test_an_empty_command_is_refused(tools):
    assert tools["bash"].run(command="   ").metadata.get("is_error")


def test_a_command_with_no_output_says_so(tools):
    assert "(no output)" in tools["bash"].run(command="true").text


# --------------------------------------------------------------------------- #
# glob
# --------------------------------------------------------------------------- #


def test_glob_finds_files(tmp_path, tools):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    assert "src/a.py" in tools["glob"].run(pattern="**/*.py").text


def test_glob_skips_noise_directories(tmp_path, tools):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.py").write_text("", encoding="utf-8")
    output = tools["glob"].run(pattern="**/*.py")
    assert "src/a.py" in output.text
    assert "node_modules" not in output.text


def test_glob_returns_newest_first(tmp_path, tools):
    import os
    import time

    for name, age in (("old.py", 10_000), ("new.py", 0)):
        path = tmp_path / name
        path.write_text("", encoding="utf-8")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    assert tools["glob"].run(pattern="*.py").text.splitlines()[0] == "new.py"


def test_glob_reports_no_matches_plainly(tools):
    output = tools["glob"].run(pattern="*.nothing")
    assert output.metadata["matches"] == 0
    assert not output.metadata.get("is_error")


def test_glob_caps_the_list_and_says_how_many_more(tmp_path, tools):
    for i in range(20):
        (tmp_path / f"f{i}.py").write_text("", encoding="utf-8")
    output = tools["glob"].run(pattern="*.py", limit=5)
    assert "15 more" in output.text


def test_an_empty_glob_pattern_is_refused(tools):
    assert tools["glob"].run(pattern="").metadata.get("is_error")


# --------------------------------------------------------------------------- #
# grep
# --------------------------------------------------------------------------- #


def test_grep_groups_hits_by_file_with_line_numbers(tmp_path, tools):
    (tmp_path / "a.py").write_text("import os\nimport sys\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import os\n", encoding="utf-8")
    output = tools["grep"].run(pattern=r"^import os")
    assert output.metadata["files"] == 2
    assert "1  import os" in output.text


def test_grep_can_be_restricted_by_glob(tmp_path, tools):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")
    assert tools["grep"].run(pattern="needle", glob="*.py").metadata["files"] == 1


def test_grep_is_case_sensitive_by_default(tmp_path, tools):
    (tmp_path / "a.py").write_text("Needle\n", encoding="utf-8")
    assert tools["grep"].run(pattern="needle").metadata["matches"] == 0
    assert tools["grep"].run(pattern="needle", ignore_case=True).metadata["matches"] == 1


def test_grep_skips_noise_directories(tmp_path, tools):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.py").write_text("needle\n", encoding="utf-8")
    assert tools["grep"].run(pattern="needle").metadata["matches"] == 0


def test_grep_stops_at_the_limit_and_says_so(tmp_path, tools):
    (tmp_path / "a.py").write_text("needle\n" * 200, encoding="utf-8")
    output = tools["grep"].run(pattern="needle", limit=10)
    assert "stopped at 10 matches" in output.text


def test_an_invalid_regex_is_reported_not_raised(tools):
    output = tools["grep"].run(pattern="(unclosed")
    assert output.metadata.get("is_error")
    assert "Invalid regular expression" in output.text


def test_grep_reports_no_matches_plainly(tools):
    assert tools["grep"].run(pattern="nothing-here").metadata["matches"] == 0


def test_an_unreadable_file_does_not_stop_the_search(tmp_path, tools):
    (tmp_path / "good.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\x00\xff" * 100)
    assert tools["grep"].run(pattern="needle").metadata["matches"] == 1


# --------------------------------------------------------------------------- #
# todo
# --------------------------------------------------------------------------- #


def test_todo_renders_progress(tools):
    output = tools["todo"].run(
        items=[
            {"task": "read", "status": "done"},
            {"task": "edit", "status": "in_progress"},
        ]
    )
    assert "[x] read" in output.text
    assert "[>] edit" in output.text
    assert output.metadata["done"] == 1


def test_todo_flags_split_focus(tools):
    output = tools["todo"].run(
        items=[
            {"task": "a", "status": "in_progress"},
            {"task": "b", "status": "in_progress"},
        ]
    )
    assert "one at a time" in output.text


def test_todo_persists_between_calls(tools):
    tools["todo"].run(items=[{"task": "one", "status": "pending"}])
    assert "one" in tools["todo"].run().text


def test_an_empty_todo_list_says_so(tools):
    assert "empty" in tools["todo"].run().text


def test_items_without_a_task_are_ignored(tools):
    output = tools["todo"].run(items=[{"status": "done"}, {"task": "real", "status": "done"}])
    assert output.metadata["total"] == 1
