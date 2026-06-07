from __future__ import annotations

import pytest

from shipit_agent import ClaudeMemoryTool
from shipit_agent.tools.base import ToolContext


@pytest.fixture
def tool(tmp_path):
    return ClaudeMemoryTool(root_dir=tmp_path)


@pytest.fixture
def ctx():
    return ToolContext(prompt="test")


def run(tool, ctx, **kwargs):
    return tool.run(ctx, **kwargs).text


def test_exports():
    from shipit_agent import tools

    assert tools.ClaudeMemoryTool is ClaudeMemoryTool


def test_schema_is_command_based(tool):
    schema = tool.schema()
    params = schema["function"]["parameters"]
    assert params["required"] == ["command"]
    enum = params["properties"]["command"]["enum"]
    assert set(enum) == {
        "view",
        "create",
        "str_replace",
        "insert",
        "delete",
        "rename",
    }


def test_full_round_trip(tool, ctx, tmp_path):
    # create
    out = run(tool, ctx, command="create", path="notes.md", file_text="line1\nline2\n")
    assert "Created" in out
    assert (tmp_path / "notes.md").read_text() == "line1\nline2\n"

    # view file (line numbers)
    out = run(tool, ctx, command="view", path="notes.md")
    assert "1\tline1" in out
    assert "2\tline2" in out

    # view directory
    out = run(tool, ctx, command="view", path=".")
    assert "notes.md" in out

    # str_replace
    out = run(tool, ctx, command="str_replace", path="notes.md",
              old_str="line1", new_str="LINE1")
    assert "Replaced 1 occurrence" in out
    assert (tmp_path / "notes.md").read_text() == "LINE1\nline2\n"

    # insert after line 1 (0 == start of file convention)
    out = run(tool, ctx, command="insert", path="notes.md",
              insert_line=1, insert_text="middle")
    assert "Inserted text after line 1" in out
    assert (tmp_path / "notes.md").read_text() == "LINE1\nmiddle\nline2\n"

    # rename
    out = run(tool, ctx, command="rename", old_path="notes.md", new_path="renamed.md")
    assert "Renamed" in out
    assert not (tmp_path / "notes.md").exists()
    assert (tmp_path / "renamed.md").exists()

    # delete
    out = run(tool, ctx, command="delete", path="renamed.md")
    assert "Deleted" in out
    assert not (tmp_path / "renamed.md").exists()


def test_insert_at_start_with_zero(tool, ctx, tmp_path):
    run(tool, ctx, command="create", path="f.txt", file_text="a\nb\n")
    run(tool, ctx, command="insert", path="f.txt", insert_line=0, insert_text="top")
    assert (tmp_path / "f.txt").read_text() == "top\na\nb\n"


def test_str_replace_requires_unique_match(tool, ctx):
    run(tool, ctx, command="create", path="dup.txt", file_text="x\nx\n")
    out = run(tool, ctx, command="str_replace", path="dup.txt",
              old_str="x", new_str="y")
    assert "Error" in out
    assert "not unique" in out


def test_str_replace_no_match(tool, ctx):
    run(tool, ctx, command="create", path="a.txt", file_text="hello\n")
    out = run(tool, ctx, command="str_replace", path="a.txt",
              old_str="absent", new_str="z")
    assert "Error" in out
    assert "not found" in out


def test_path_traversal_rejected(tool, ctx):
    out = run(tool, ctx, command="create", path="../escape.txt", file_text="nope")
    assert "Error" in out
    assert "escapes the memory root" in out


def test_absolute_path_outside_root_rejected(tool, ctx):
    out = run(tool, ctx, command="view", path="/etc/passwd")
    assert "Error" in out
    assert "escapes the memory root" in out


def test_view_missing_file(tool, ctx):
    out = run(tool, ctx, command="view", path="ghost.txt")
    assert "Error" in out


def test_unknown_command(tool, ctx):
    out = run(tool, ctx, command="frobnicate")
    assert "Error" in out
    assert "unsupported" in out


def test_construction_does_not_create_root(tmp_path):
    root = tmp_path / "mem_root"
    ClaudeMemoryTool(root_dir=root)
    assert not root.exists()
