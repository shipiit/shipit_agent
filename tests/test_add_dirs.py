"""add_dirs: folders beside the project the file tools may use, as in the SDK.

Relative paths still mean the project root. An absolute path is allowed
under the root or one of the added folders, after resolving symlinks and
"..", and refused anywhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shipit_agent.llms import LLMResponse
from shipit_agent.sdk import AgentOptions, build_agent
from shipit_agent.tools.base import ToolContext


class Quiet:
    model = "m"

    def complete(self, **_):
        return LLMResponse(content="ok")


@pytest.fixture
def setup(tmp_path: Path):
    project, shared, secret = tmp_path / "project", tmp_path / "shared", tmp_path / "secret"
    for folder in (project, shared, secret):
        folder.mkdir()
    (project / "app.py").write_text("print('app')\n")
    (shared / "lib.py").write_text("SHARED = 1\n")
    (secret / "key.txt").write_text("do not read\n")
    agent = build_agent(AgentOptions(llm=Quiet(), cwd=project, add_dirs=[shared]))
    tools = {t.name: t for t in agent.tools}
    return tools, project, shared, secret


#: One context for the test, as a run shares one: edit_file needs the read before it.
_CONTEXT = ToolContext(prompt="")


def _run(tool, **kwargs) -> str:
    """The tool's text, or the error it raised (the loop reports that as a tool error)."""
    try:
        return tool.run(_CONTEXT, **kwargs).text
    except ValueError as exc:
        return str(exc)


def test_the_file_tools_work_in_an_added_folder(setup) -> None:
    tools, project, shared, _ = setup
    assert "SHARED = 1" in _run(tools["read_file"], path=str(shared / "lib.py"))
    _run(tools["edit_file"], path=str(shared / "lib.py"), old_text="SHARED = 1", new_text="SHARED = 2")
    assert (shared / "lib.py").read_text() == "SHARED = 2\n"
    _run(tools["write_file"], path=str(shared / "new.py"), content="NEW = True\n")
    assert (shared / "new.py").read_text() == "NEW = True\n"
    assert str(shared / "lib.py") in _run(tools["glob_files"], pattern="*.py", path=str(shared))
    assert "SHARED = 2" in _run(tools["grep_files"], pattern="SHARED", path=str(shared))


def test_relative_paths_still_mean_the_project(setup) -> None:
    tools, *_ = setup
    assert "print('app')" in _run(tools["read_file"], path="app.py")


@pytest.mark.parametrize("escape", ["secret_abs", "dotdot", "symlink"])
def test_anything_outside_every_allowed_folder_is_refused(setup, escape: str) -> None:
    tools, project, shared, secret = setup
    if escape == "symlink":
        os.symlink(secret / "key.txt", shared / "link.txt")
        target = str(shared / "link.txt")
    else:
        target = str(secret / "key.txt") if escape == "secret_abs" else str(shared / ".." / "secret" / "key.txt")
    out = _run(tools["read_file"], path=target)
    assert "do not read" not in out and "escapes" in out.lower()
    assert not (secret / "w.txt").exists()
    _run(tools["write_file"], path=str(secret / "w.txt"), content="x")
    assert not (secret / "w.txt").exists()


def test_without_add_dirs_an_absolute_path_beside_the_project_is_refused(tmp_path: Path) -> None:
    (tmp_path / "project").mkdir()
    (tmp_path / "other.txt").write_text("outside\n")
    agent = build_agent(AgentOptions(llm=Quiet(), cwd=tmp_path / "project"))
    read = next(t for t in agent.tools if t.name == "read_file")
    assert "outside" not in _run(read, path=str(tmp_path / "other.txt"))
