from __future__ import annotations

from shipit_agent import Agent, TodoTool
from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.tools.base import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(prompt="do work")


def test_schema_shape() -> None:
    schema = TodoTool().schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "todo"
    params = fn["parameters"]
    assert params["required"] == ["todos"]
    todos = params["properties"]["todos"]
    assert todos["type"] == "array"
    item = todos["items"]
    assert item["required"] == ["content"]
    assert item["properties"]["status"]["enum"] == [
        "pending",
        "in_progress",
        "completed",
    ]


def test_happy_path_renders_and_sets_state() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(
        ctx,
        todos=[
            {"content": "Read the spec", "status": "completed"},
            {"content": "Write the tool", "status": "in_progress"},
            {"content": "Run the tests", "status": "pending"},
        ],
    )

    # state is set with the normalized list
    assert ctx.state["todos"] == [
        {"content": "Read the spec", "status": "completed"},
        {"content": "Write the tool", "status": "in_progress"},
        {"content": "Run the tests", "status": "pending"},
    ]

    # rendered checklist uses the status glyphs
    assert "☑ Read the spec" in out.text
    assert "▶ Write the tool" in out.text
    assert "☐ Run the tests" in out.text

    # metadata carries todos + summary, and opts out of persistence
    assert out.metadata["persist"] is False
    assert out.metadata["todos"] == ctx.state["todos"]
    assert out.metadata["summary"] == {
        "total": 3,
        "completed": 1,
        "in_progress": 1,
        "pending": 1,
    }


def test_replace_semantics() -> None:
    tool = TodoTool()
    ctx = _ctx()
    tool.run(ctx, todos=[{"content": "first", "status": "in_progress"}])
    out = tool.run(
        ctx,
        todos=[
            {"content": "first", "status": "completed"},
            {"content": "second", "status": "in_progress"},
        ],
    )
    # second call fully overwrites the previous list
    assert ctx.state["todos"] == [
        {"content": "first", "status": "completed"},
        {"content": "second", "status": "in_progress"},
    ]
    assert out.metadata["summary"]["total"] == 2


def test_status_coercion_defaults_to_pending() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(
        ctx,
        todos=[
            {"content": "no status here"},
            {"content": "blank status", "status": ""},
        ],
    )
    assert ctx.state["todos"] == [
        {"content": "no status here", "status": "pending"},
        {"content": "blank status", "status": "pending"},
    ]
    assert out.metadata["summary"]["pending"] == 2


def test_content_whitespace_stripped() -> None:
    tool = TodoTool()
    ctx = _ctx()
    tool.run(ctx, todos=[{"content": "  padded  ", "status": "pending"}])
    assert ctx.state["todos"][0]["content"] == "padded"


def test_unknown_status_is_error() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(ctx, todos=[{"content": "x", "status": "wip"}])
    assert "error" in out.metadata
    assert "wip" in out.metadata["error"]
    # state untouched on bad input
    assert "todos" not in ctx.state


def test_empty_content_is_error() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(ctx, todos=[{"content": "   "}])
    assert "error" in out.metadata
    assert "todos" not in ctx.state


def test_todos_not_a_list_is_error() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(ctx, todos="not a list")
    assert "error" in out.metadata
    assert out.metadata["persist"] is False
    assert "todos" not in ctx.state


def test_empty_list_is_valid() -> None:
    tool = TodoTool()
    ctx = _ctx()
    out = tool.run(ctx, todos=[])
    assert ctx.state["todos"] == []
    assert "error" not in out.metadata
    assert out.metadata["summary"] == {
        "total": 0,
        "completed": 0,
        "in_progress": 0,
        "pending": 0,
    }


def test_builtin_map_includes_todo() -> None:
    tool_map = get_builtin_tool_map()
    assert "todo" in tool_map
    assert isinstance(tool_map["todo"], TodoTool)


def test_with_builtins_includes_todo() -> None:
    agent = Agent.with_builtins(llm=SimpleEchoLLM())
    names = {getattr(t, "name", None) for t in agent.tools}
    assert "todo" in names
