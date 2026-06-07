"""Temp-file leak regression test for CodeExecutionTool (LOW).

NamedTemporaryFile(delete=False) never self-cleaned, so each run leaked a
script into the workspace. The tool now removes it in a finally block.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.code_execution.code_execution_tool import CodeExecutionTool


def _ctx() -> ToolContext:
    return ToolContext(prompt="t", state={})


@pytest.mark.skipif(
    shutil.which("python3") is None and shutil.which("python") is None,
    reason="no python interpreter on PATH",
)
def test_temp_script_is_removed_after_run(tmp_path: Path) -> None:
    tool = CodeExecutionTool(workspace_root=tmp_path)
    result = tool.run(_ctx(), language="python", code="print('hi')")
    script_path = Path(result.metadata["script_path"])
    assert not script_path.exists()
    # No leftover .py scripts in the workspace.
    assert list(tmp_path.glob("*.py")) == []
