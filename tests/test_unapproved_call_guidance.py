"""A call that needs approval nobody can give says so, and what to do instead.

Gemma, told only "requires human approval", retried `rm` three times and
then asked for confirmation in text until it ran out of turns.
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent import Agent
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.bash import BashTool


class Scripted:
    model = "m"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, **_):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(tool_calls=[ToolCall(name="bash", arguments={"command": "rm scratch.py"})])
        return LLMResponse(content="done")


def test_an_unapprovable_call_tells_the_model_to_move_on(tmp_path: Path) -> None:
    (tmp_path / "scratch.py").write_text("x = 1\n")
    agent = Agent(llm=Scripted(), tools=[BashTool(root_dir=tmp_path)], project_root=tmp_path,
                  auto_use_skills=False, auto_project_memory=False, auto_project_skills=False)
    result = agent.run("Clean up.")
    note = next(m.content for m in result.messages if m.role == "tool")
    assert (tmp_path / "scratch.py").exists()
    assert "requires human approval" in note and "deletes files" in note
    assert "NOT run" in note and "no one can approve" in note
    assert "do not retry" in note.lower() and "say in your answer" in note
