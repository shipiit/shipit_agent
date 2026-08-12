from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.file_read.file_read_tool import FileReadTool


def test_invalid_start_line_is_a_recoverable_tool_result(tmp_path) -> None:
    (tmp_path / "app.py").write_text("one\ntwo\n", encoding="utf-8")

    result = FileReadTool(root_dir=tmp_path).run(
        ToolContext(prompt="inspect"),
        path="app.py",
        start_line='155} biopsies: [":155',
    )

    assert result.metadata == {"error": "invalid_argument", "argument": "start_line"}
    assert "call read_file again" in result.text


def test_invalid_max_lines_is_a_recoverable_tool_result(tmp_path) -> None:
    (tmp_path / "app.py").write_text("one\ntwo\n", encoding="utf-8")

    result = FileReadTool(root_dir=tmp_path).run(
        ToolContext(prompt="inspect"),
        path="app.py",
        max_lines={"bad": "shape"},
    )

    assert result.metadata == {"error": "invalid_argument", "argument": "max_lines"}


def test_numeric_line_ranges_still_work(tmp_path) -> None:
    (tmp_path / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = FileReadTool(root_dir=tmp_path).run(
        ToolContext(prompt="inspect"),
        path="app.py",
        start_line="2",
        max_lines="1",
    )

    assert result.text == "    2: two"
    assert result.metadata["start_line"] == 2
