"""An edit still applies after an outside change, as long as its target is intact.

Edits are exact-text replacements against the file as it is now, so a
formatter or a teammate touching another part of the file is no reason to
refuse. Only when the text the edit targets is gone does the model need to
read the file again.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.edit_file.edit_file_tool import EditFileTool
from shipit_agent.tools.edit_file.multi_edit_tool import MultiEditTool
from shipit_agent.tools.file_state import record_file_seen


@pytest.fixture
def seen(tmp_path: Path) -> tuple[Path, ToolContext]:
    path = tmp_path / "app.py"
    path.write_text("def greet():\n    return 'hi'\n")
    context = ToolContext(
        prompt="t", state={"read_files": set(), "read_file_mtimes": {}}
    )
    record_file_seen(context.state, path)
    return path, context


def _change_outside(path: Path, text: str) -> None:
    path.write_text(text)
    later = time.time() + 5
    os.utime(path, (later, later))


def test_an_edit_applies_when_its_target_survived(seen) -> None:
    path, context = seen
    _change_outside(path, "import os\n\ndef greet():\n    return 'hi'\n")

    out = EditFileTool(root_dir=path.parent).run(
        context, path="app.py", old_text="return 'hi'", new_text="return 'hello'"
    )

    assert not out.metadata.get("is_error")
    assert path.read_text() == "import os\n\ndef greet():\n    return 'hello'\n"
    assert "changed on disk" in out.text
    assert out.metadata["changed_since_read"] is True


def test_an_edit_whose_target_is_gone_asks_for_a_reread(seen) -> None:
    path, context = seen
    _change_outside(path, "def greet():\n    return 'hey'\n")

    out = EditFileTool(root_dir=path.parent).run(
        context, path="app.py", old_text="return 'hi'", new_text="return 'hello'"
    )

    assert out.metadata["error"] == "stale_read"
    assert path.read_text() == "def greet():\n    return 'hey'\n"


def test_an_unchanged_file_edits_without_a_note(seen) -> None:
    path, context = seen
    out = EditFileTool(root_dir=path.parent).run(
        context, path="app.py", old_text="return 'hi'", new_text="return 'yo'"
    )
    assert "changed on disk" not in out.text
    assert out.metadata.get("changed_since_read") is False


def test_multi_edit_applies_when_every_target_survived(seen) -> None:
    path, context = seen
    _change_outside(path, "# header\ndef greet():\n    return 'hi'\n")

    out = MultiEditTool(root_dir=path.parent).run(
        context,
        path="app.py",
        edits=[
            {"old_text": "def greet", "new_text": "def welcome"},
            {"old_text": "'hi'", "new_text": "'hello'"},
        ],
    )

    assert not out.metadata.get("is_error")
    assert path.read_text() == "# header\ndef welcome():\n    return 'hello'\n"
    assert "changed on disk" in out.text


def test_multi_edit_whose_target_is_gone_writes_nothing(seen) -> None:
    path, context = seen
    _change_outside(path, "def greet():\n    return 'hey'\n")

    out = MultiEditTool(root_dir=path.parent).run(
        context, path="app.py", edits=[{"old_text": "'hi'", "new_text": "'hello'"}]
    )

    assert out.metadata["error"] == "stale_read"
    assert path.read_text() == "def greet():\n    return 'hey'\n"
