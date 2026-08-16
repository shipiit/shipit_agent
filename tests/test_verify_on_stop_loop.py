"""Verify-on-stop, end to end through the real sync loop: a turn that edits code
without passing tests is sent back to run them; once they pass, it finishes. And
off by default, nothing changes."""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolContext, ToolOutput


class EditTool:
    """A non-read-only tool that actually writes the file it reports editing —
    the gate only counts a path that exists on disk (a real edit, not a plan)."""

    name = "edit_file"

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        from pathlib import Path

        path = str(kwargs.get("path", "app.py"))
        Path(path).write_text("print('hi')\n", encoding="utf-8")
        return ToolOutput(text="edited", metadata={"path": path})


class BashTool:
    """A shell tool that reports command + exit_code (like the real bash tool)."""

    name = "bash"

    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "parameters": {
            "type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        cmd = kwargs.get("command", "")
        return ToolOutput(
            text=f"exit_code: {self.exit_code}",
            metadata={"command": cmd, "exit_code": self.exit_code, "ok": self.exit_code == 0},
        )


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        if self.i < len(self.script):
            step = self.script[self.i]
            self.i += 1
            if step is None:
                return LLMResponse(content="Done — all set.")
            name, args = step
            return LLMResponse(tool_calls=[ToolCall(name=name, arguments=args)])
        return LLMResponse(content="Done — all set.")


def _runtime(project, llm, tools, *, verify):
    return AgentRuntime(
        llm=llm, prompt="You are a coding agent.", tools=tools,
        max_iterations=8,
        tool_output_dir=str(project / ".shipit" / "tool-results"),
        verify_before_stop=verify,
    )


def test_edited_code_is_sent_back_to_verify(tmp_path):
    (tmp_path / "tests").mkdir()          # → pytest is the verify command
    # Edit, then immediately try to finish. The gate should send it back.
    passing_bash = BashTool(exit_code=0)
    llm = ScriptedLLM([
        ("edit_file", {"path": str(tmp_path / "app.py")}),  # edit code
        None,                                # try to finish → verify nudge fires
        ("bash", {"command": "pytest -q"}),  # model runs the tests (pass)
        None,                                # finish for real
    ])
    state, response = _runtime(tmp_path, llm, [EditTool(), passing_bash], verify=True).run("fix the bug")

    # It did NOT stop at the first attempt — a verify_required event fired.
    assert any(e.type == "verify_required" for e in state.events)
    # And it finished only after the passing test run.
    assert "all set" in (response.content or "").lower()
    assert llm.i >= 4                        # walked the whole script


def test_docs_only_edit_is_not_gated(tmp_path):
    (tmp_path / "tests").mkdir()
    llm = ScriptedLLM([("edit_file", {"path": str(tmp_path / "README.md")}), None])
    state, response = _runtime(tmp_path, llm, [EditTool()], verify=True).run("update docs")
    assert not any(e.type == "verify_required" for e in state.events)  # README needs no test
    assert "all set" in (response.content or "").lower()


def test_off_by_default_never_gates(tmp_path):
    (tmp_path / "tests").mkdir()
    llm = ScriptedLLM([("edit_file", {"path": str(tmp_path / "app.py")}), None])
    state, response = _runtime(tmp_path, llm, [EditTool()], verify=False).run("fix it")
    assert not any(e.type == "verify_required" for e in state.events)  # feature off
    assert "all set" in (response.content or "").lower()


def test_no_edit_never_gates(tmp_path):
    (tmp_path / "tests").mkdir()
    llm = ScriptedLLM([None])                # answers immediately, no tools
    state, _ = _runtime(tmp_path, llm, [EditTool()], verify=True).run("what is 2+2?")
    assert not any(e.type == "verify_required" for e in state.events)
