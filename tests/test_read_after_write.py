"""A read after a write must see the new state.

The duplicate-call gate skips an exact repeat of a read-only call. That is
safe only while nothing has changed: once a mutating tool runs (an edit, a
write, a shell command), an earlier read may describe a file that no longer
exists in that form. Re-reading after an edit is how an agent checks its own
work, so it must run, and a file the agent just wrote counts as read.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from shipit_agent.agent import Agent
from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.llms.base import LLMResponse, ToolCall


def _call(name: str, **arguments) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name=name, arguments=arguments)])


class _ScriptedLLM:
    """Replays tool calls, then answers; records each tool result it is sent."""

    def __init__(self, steps: list[LLMResponse]) -> None:
        self.steps = list(steps)
        self.tool_results: list[str] = []

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        tool_messages = [m for m in messages if m.role == "tool"]
        if tool_messages:
            self.tool_results.append(str(tool_messages[-1].content))
        return self.steps.pop(0) if self.steps else LLMResponse(content="done")


def _agent(llm, root: Path, *names: str) -> Agent:
    tool_map = get_builtin_tool_map(project_root=str(root), workspace_root=str(root))
    return Agent(llm=llm, tools=[tool_map[n] for n in names], auto_use_skills=False)


def test_rereading_a_file_after_editing_it_returns_the_new_contents(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    llm = _ScriptedLLM([
        _call("read_file", path="app.py"),
        _call("edit_file", path="app.py", old_text="x = 1", new_text="x = 2"),
        _call("read_file", path="app.py"),
    ])

    _agent(llm, tmp_path, "read_file", "edit_file").run("fix it")

    reread = llm.tool_results[2]
    assert "Already ran" not in reread
    assert "x = 2" in reread


def test_an_identical_read_with_no_change_in_between_is_still_skipped(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    llm = _ScriptedLLM([
        _call("read_file", path="app.py"),
        _call("read_file", path="app.py"),
    ])

    _agent(llm, tmp_path, "read_file").run("look")

    assert "Already ran" in llm.tool_results[1]


def test_a_failed_mutation_does_not_unlock_repeats(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    llm = _ScriptedLLM([
        _call("read_file", path="app.py"),
        _call("edit_file", path="app.py", old_text="not there", new_text="y"),
        _call("read_file", path="app.py"),
    ])

    _agent(llm, tmp_path, "read_file", "edit_file").run("fix it")

    assert "not found" in llm.tool_results[1]
    assert "Already ran" in llm.tool_results[2]


def test_a_file_the_agent_wrote_can_be_edited_without_reading_it(tmp_path):
    llm = _ScriptedLLM([
        _call("write_file", path="notes.md", content="hello world\n"),
        _call("edit_file", path="notes.md", old_text="hello", new_text="hi"),
    ])

    _agent(llm, tmp_path, "write_file", "edit_file").run("write then edit")

    assert "Edit blocked" not in llm.tool_results[1]
    assert (tmp_path / "notes.md").read_text() == "hi world\n"


def test_async_runtime_rereads_after_an_edit(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    llm = _ScriptedLLM([
        _call("read_file", path="app.py"),
        _call("edit_file", path="app.py", old_text="x = 1", new_text="x = 2"),
        _call("read_file", path="app.py"),
    ])
    agent = _agent(llm, tmp_path, "read_file", "edit_file")
    if not hasattr(agent, "arun"):
        pytest.skip("Agent has no async entry point")

    asyncio.run(agent.arun("fix it"))

    assert "Already ran" not in llm.tool_results[2]
    assert "x = 2" in llm.tool_results[2]
