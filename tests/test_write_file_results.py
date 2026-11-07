"""write_file says what it did, and refuses a path outside the project plainly."""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.file_write.file_write_tool import FileWriteTool


def _write(tmp_path: Path, **kwargs):
    return FileWriteTool(root_dir=tmp_path).run(ToolContext(prompt="t"), **kwargs)


def test_a_new_file_is_created(tmp_path: Path) -> None:
    out = _write(tmp_path, path="notes.md", content="hello\n")
    assert out.text.startswith("Created notes.md")
    assert out.metadata["created"] is True


def test_an_existing_file_is_overwritten(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("old")
    out = _write(tmp_path, path="notes.md", content="new\n")
    assert out.text.startswith("Overwrote notes.md")
    assert out.metadata["created"] is False


def test_append_says_so(tmp_path: Path) -> None:
    (tmp_path / "log.txt").write_text("a\n")
    out = _write(tmp_path, path="log.txt", content="b\n", mode="append")
    assert out.text.startswith("Appended to log.txt")
    assert (tmp_path / "log.txt").read_text() == "a\nb\n"


def test_the_size_is_reported_in_lines(tmp_path: Path) -> None:
    out = _write(tmp_path, path="three.txt", content="1\n2\n3\n")
    assert "3 lines" in out.text


def test_a_path_outside_the_project_is_an_error_result(tmp_path: Path) -> None:
    out = _write(tmp_path, path="../outside.txt", content="x")
    assert out.metadata["is_error"] is True
    assert out.metadata["error"] == "outside_project"
    assert "inside the project" in out.text
    assert not (tmp_path.parent / "outside.txt").exists()
