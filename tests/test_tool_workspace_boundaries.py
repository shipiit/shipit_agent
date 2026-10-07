import pytest

from shipit_agent.tools._shared import Workspace
from shipit_agent.tools.edit_file import EditFileTool
from shipit_agent.tools.base import ToolContext


def test_workspace_rejects_prefix_sibling_and_symlink_escape(tmp_path):
    root = tmp_path / "project"
    sibling = tmp_path / "project-backup"
    root.mkdir()
    sibling.mkdir()
    workspace = Workspace(root=root)
    for path in ("../project-backup/secret.txt", str(sibling / "secret.txt")):
        with pytest.raises(ValueError, match="outside"):
            workspace.resolve(path)
    (root / "link").symlink_to(sibling, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        workspace.resolve("link/secret.txt")
    assert workspace.resolve("src/app.py") == root / "src/app.py"


@pytest.mark.parametrize("replace_all", [False, True])
def test_empty_edit_cannot_insert_between_every_character(tmp_path, replace_all):
    path = tmp_path / "app.py"
    path.write_text("print('hello')\n")
    context = ToolContext(prompt="edit", state={"read_files": [str(path)]})
    output = EditFileTool(root_dir=tmp_path).run(
        context, path="app.py", old_text="", new_text="oops", replace_all=replace_all,
    )
    assert output.metadata["is_error"] is True
    assert path.read_text() == "print('hello')\n"
