"""Tests for NotebookEditTool — structural .ipynb editing."""

from __future__ import annotations

import json

from shipit_agent.tools import NotebookEditTool
from shipit_agent.tools.base import ToolContext

CTX = ToolContext(prompt="", system_prompt="", state={})


def _nb(tmp_path, cells):
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    p = tmp_path / "demo.ipynb"
    p.write_text(json.dumps(nb))
    return p


def _cells(p):
    return json.loads(p.read_text())["cells"]


def _tool(tmp_path):
    return NotebookEditTool(root_dir=tmp_path)


CODE = {"cell_type": "code", "metadata": {}, "execution_count": 2,
        "source": ["print('hi')\n", "x = 1"], "outputs": [
            {"output_type": "stream", "text": ["hi\n"]}]}
MD = {"cell_type": "markdown", "metadata": {}, "source": "# Title"}


class TestReadOnly:
    def test_list(self, tmp_path) -> None:
        _nb(tmp_path, [MD, CODE])
        out = _tool(tmp_path).run(CTX, path="demo.ipynb", action="list")
        assert "2 cells" in out.text
        assert "markdown" in out.text and "# Title" in out.text
        assert "[2]" in out.text  # execution count shown

    def test_read_with_outputs(self, tmp_path) -> None:
        _nb(tmp_path, [CODE])
        out = _tool(tmp_path).run(CTX, path="demo.ipynb", action="read", index=0)
        assert "print('hi')" in out.text and "x = 1" in out.text
        assert "--- outputs ---" in out.text and "hi" in out.text

    def test_bad_index(self, tmp_path) -> None:
        _nb(tmp_path, [MD])
        out = _tool(tmp_path).run(CTX, path="demo.ipynb", action="read", index=9)
        assert out.metadata["ok"] is False


class TestMutations:
    def test_edit_preserves_others(self, tmp_path) -> None:
        p = _nb(tmp_path, [MD, CODE])
        out = _tool(tmp_path).run(CTX, path="demo.ipynb", action="edit",
                                  index=1, source="y = 2\n")
        assert out.metadata["ok"] is True
        cells = _cells(p)
        assert cells[1]["source"] == "y = 2\n"
        assert cells[0]["source"] == "# Title"          # untouched
        assert cells[1]["outputs"]                       # outputs preserved

    def test_add_append_and_insert(self, tmp_path) -> None:
        p = _nb(tmp_path, [MD])
        tool = _tool(tmp_path)
        tool.run(CTX, path="demo.ipynb", action="add", source="a = 1")
        tool.run(CTX, path="demo.ipynb", action="add", index=0,
                 source="# First", cell_type="markdown")
        cells = _cells(p)
        assert cells[0]["source"] == "# First"
        assert cells[-1]["source"] == "a = 1"
        assert cells[-1]["outputs"] == []                # code scaffold

    def test_delete_and_clear_outputs(self, tmp_path) -> None:
        p = _nb(tmp_path, [MD, dict(CODE)])
        tool = _tool(tmp_path)
        tool.run(CTX, path="demo.ipynb", action="clear_outputs")
        assert _cells(p)[1]["outputs"] == []
        assert _cells(p)[1]["execution_count"] is None
        tool.run(CTX, path="demo.ipynb", action="delete", index=0)
        assert len(_cells(p)) == 1


class TestGuards:
    def test_path_escape_blocked(self, tmp_path) -> None:
        out = _tool(tmp_path).run(CTX, path="../../etc/passwd", action="list")
        assert out.metadata["ok"] is False
        assert "escapes" in out.text

    def test_invalid_json(self, tmp_path) -> None:
        (tmp_path / "bad.ipynb").write_text("not json")
        out = _tool(tmp_path).run(CTX, path="bad.ipynb", action="list")
        assert out.metadata["ok"] is False

    def test_in_builtin_catalogue(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = [t.name for t in get_builtin_tools(project_root=".")]
        assert "notebook_edit" in names
