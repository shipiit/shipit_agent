"""Parity upgrades: compaction read-gate reset, larger read window,
higher iteration budget, and the end-of-run summary event.
"""

from __future__ import annotations

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_core import RuntimeCore
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.edit_file import EditFileTool
from shipit_agent.tools.file_read import FileReadTool


class EchoLLM:
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(content="done", usage={"total_tokens": 7})


# ── #1 compaction resets the read-before-edit gate ───────────────────────


def test_compaction_resets_the_read_gate():
    shared = {"read_files": ["/x/a.py"], "read_file_mtimes": {"/x/a.py": 123}}
    RuntimeCore._reset_read_gate(shared)
    assert shared["read_files"] == []
    assert shared["read_file_mtimes"] == {}


def test_edit_blocked_after_compaction_forces_a_reread(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("original\n")
    state: dict = {}
    reader = FileReadTool(root_dir=str(tmp_path))
    editor = EditFileTool(root_dir=str(tmp_path))
    ctx = ToolContext(prompt="", state=state)

    reader.run(ctx, path="a.py")
    assert "a.py" in " ".join(state["read_files"])  # gate populated

    # Compaction summarized the read away.
    RuntimeCore._reset_read_gate(state)

    out = editor.run(ctx, path="a.py", old_text="original", new_text="changed")
    assert "read the file first" in out.text.lower()


# ── #7 larger read window ────────────────────────────────────────────────


def test_read_file_returns_up_to_2000_lines(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line {i}" for i in range(1500)))
    out = FileReadTool(root_dir=str(tmp_path)).run(
        ToolContext(prompt="", state={}), path="big.py"
    )
    assert out.metadata["returned_lines"] == 1500  # not clipped at 250


# ── #2 iteration budget ──────────────────────────────────────────────────


def test_default_iteration_budget_is_higher():
    agent = Agent(
        llm=EchoLLM(),
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
    )
    assert agent.max_iterations >= 12


# ── #9 end-of-run summary ────────────────────────────────────────────────


class ToolThenDoneLLM:
    def __init__(self):
        self.turn = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name="noop", arguments={})],
                               usage={"total_tokens": 5})
        return LLMResponse(content="done", usage={"total_tokens": 5})


class NoopTool:
    name = "noop"
    description = "noop"
    read_only = True

    def schema(self):
        return {"type": "function", "function": {"name": "noop", "description": "noop",
                "parameters": {"type": "object", "properties": {}}}}

    def run(self, context, **kwargs):
        return ToolOutput(text="ok")


def test_run_summary_event_is_emitted_with_accounting():
    runtime = AgentRuntime(
        llm=ToolThenDoneLLM(),
        prompt="You are helpful.",
        tools=[NoopTool()],
        max_iterations=3,
    )
    state, _ = runtime.run("go")
    summaries = [e for e in state.events if e.type == "run_summary"]
    assert summaries, "no run_summary emitted"
    payload = summaries[0].payload
    assert payload["tool_calls"] == 1
    assert payload["iterations"] >= 2
    assert "usage" in payload
    assert "Run finished" in summaries[0].message
    # run_completed carries the summary too.
    completed = [e for e in state.events if e.type == "run_completed"][0]
    assert completed.payload["summary"]["tool_calls"] == 1


def test_run_summary_is_canonical_for_reconnecting_clients():
    from shipit_agent.streaming import Durability, classify

    assert classify("run_summary") is Durability.CANONICAL


# ── #8 compaction re-grounding ───────────────────────────────────────────


def test_compaction_regrounds_recent_files(tmp_path):
    from shipit_agent.runtime_core import RuntimeCore

    f = tmp_path / "mod.py"
    f.write_text("def current(): return 42\n")
    state = {"read_files": [str(f)], "read_file_mtimes": {str(f): 1}}
    # A compaction summarized the read away...
    RuntimeCore._reset_read_gate(state)
    assert state["read_files"] == []
    # ...re-grounding re-reads the file as a fresh message.
    msgs = RuntimeCore.regrounding_messages(state)
    assert msgs, "no re-grounding message produced"
    assert "def current()" in msgs[0].content
    assert msgs[0].metadata.get("regrounding") is True
    # And the read-gate is restored for that file so an edit can follow.
    assert str(f) in state["read_files"]
    # Fires once — the hint is consumed.
    assert RuntimeCore.regrounding_messages(state) == []
