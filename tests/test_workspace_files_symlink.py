"""workspace_files lists a workspace reached through a symlink.

On macOS the temp folder is a symlink (/var -> /private/var); a workspace there
listed its files relative to the unresolved root and raised ValueError.
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.workspace_files.workspace_files_tool import WorkspaceFilesTool

CONTEXT = ToolContext(prompt="")


def test_list_works_through_a_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    tool = WorkspaceFilesTool(root_dir=link)
    tool.run(CONTEXT, action="write", path="notes/a.txt", content="hi")
    out = tool.run(CONTEXT, action="list")
    assert out.metadata["items"] == ["notes"]
    assert tool.run(CONTEXT, action="list", path="notes").metadata["items"] == ["notes/a.txt"]


def test_an_empty_workspace_lists_nothing(tmp_path: Path) -> None:
    out = WorkspaceFilesTool(root_dir=tmp_path / "ws").run(CONTEXT, action="list")
    assert out.metadata["items"] == []
