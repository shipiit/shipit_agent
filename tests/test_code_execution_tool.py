from pathlib import Path

from shipit_agent.tools.code_execution import CodeExecutionTool


def test_code_execution_tool_schema_lists_multiple_languages() -> None:
    tool = CodeExecutionTool()
    enum_values = tool.schema()["function"]["parameters"]["properties"]["language"]["enum"]
    assert "python" in enum_values
    assert "javascript" in enum_values
    assert "ruby" in enum_values
    assert "typescript" in enum_values


def test_code_execution_tool_runs_python(tmp_path: Path) -> None:
    tool = CodeExecutionTool(workspace_root=tmp_path)
    result = tool.run(
        context=type("Ctx", (), {"state": {}})(),
        language="python",
        code="print('shipit')",
    )
    assert result.metadata["exit_code"] == 0
    assert "shipit" in result.metadata["stdout"]
    assert result.metadata["script_path"].endswith(".py")


def test_code_execution_tool_normalizes_language_aliases(tmp_path: Path) -> None:
    tool = CodeExecutionTool(workspace_root=tmp_path)
    result = tool.run(
        context=type("Ctx", (), {"state": {}})(),
        language="python3",
        code="print('alias-ok')",
    )
    assert result.metadata["language"] == "python"
    assert "alias-ok" in result.metadata["stdout"]
