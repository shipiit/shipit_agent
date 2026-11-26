"""An edit with nothing to match is refused: it must never be inserted between every character."""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file import EditFileTool
from shipit_agent.tools.edit_file.multi_edit_tool import MultiEditTool

ORIGINAL = "print('hello')\n"


@pytest.fixture
def target(tmp_path: Path) -> tuple[Path, ToolContext]:
    root = tmp_path.resolve()
    path = root / "app.py"
    path.write_text(ORIGINAL)
    return path, ToolContext(prompt="edit", state={"read_files": [str(path)]})


@pytest.mark.parametrize("replace_all", [False, True])
@pytest.mark.parametrize("kwargs", [{"old_text": ""}, {}], ids=["empty", "missing"])
def test_edit_file_refuses_an_empty_match(target: tuple[Path, ToolContext], replace_all: bool,
                                          kwargs: dict[str, str]) -> None:
    path, context = target
    out = EditFileTool(root_dir=path.parent).run(context, path="app.py", new_text="oops", replace_all=replace_all, **kwargs)
    assert out.metadata["is_error"] is True and out.metadata["error"] == "empty_old_text"
    assert "write_file" in out.text
    assert path.read_text() == ORIGINAL


@pytest.mark.parametrize("replace_all", [False, True])
def test_multi_edit_refuses_an_empty_match_and_writes_nothing(target: tuple[Path, ToolContext], replace_all: bool) -> None:
    path, context = target
    edits = [{"old_text": "hello", "new_text": "bye"}, {"old_text": "", "new_text": "oops", "replace_all": replace_all}]
    out = MultiEditTool(root_dir=path.parent).run(context, path="app.py", edits=edits)
    assert out.metadata["is_error"] is True and out.metadata["error"] == "empty_old_text"
    assert out.metadata["failed_edit"] == 2
    assert path.read_text() == ORIGINAL  # the first edit is not half-applied


def test_a_real_replace_all_still_works(target: tuple[Path, ToolContext]) -> None:
    path, context = target
    path.write_text("a b a\n")
    out = EditFileTool(root_dir=path.parent).run(context, path="app.py", old_text="a", new_text="c", replace_all=True)
    assert not out.metadata.get("is_error") and path.read_text() == "c b c\n"
