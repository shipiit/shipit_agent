"""Clearing through a real Agent run: the request shrinks, the history does not."""

from __future__ import annotations

from pathlib import Path

from shipit_agent import Agent
from shipit_agent.context.tool_result_clearing import ToolResultClearing
from shipit_agent.core.models import ToolCall
from shipit_agent.llms import LLMResponse
from shipit_agent.tools.file_read.file_read_tool import FileReadTool


class Reader:
    """Reads six large files one per turn, then answers; records each request."""

    model = "scripted"

    def __init__(self) -> None:
        self.requests: list[list] = []

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, text_delta_callback=None, **_):
        self.requests.append(list(messages))
        reads = sum(1 for m in messages if m.role == "tool")
        if reads < 6:
            return LLMResponse(tool_calls=[ToolCall(id=f"r{reads}", name="read_file", arguments={"path": f"f{reads}.txt"})])
        return LLMResponse(content="done")


def _run(tmp_path: Path, clearing) -> tuple[Reader, object]:
    for n in range(6):
        (tmp_path / f"f{n}.txt").write_text(f"FILE{n} " + "word " * 3_000)
    llm = Reader()
    agent = Agent(llm=llm, tools=[FileReadTool(root_dir=tmp_path)], project_root=tmp_path,
                  auto_use_skills=False, clear_tool_results=clearing)
    return llm, agent.run("read them all")


def test_with_clearing_later_requests_drop_old_file_contents(tmp_path: Path) -> None:
    llm, result = _run(tmp_path, ToolResultClearing(trigger_tokens=6_000, keep=2))
    last = "\n".join(str(m.content) for m in llm.requests[-1])
    assert "FILE5" in last and "FILE4" in last          # the newest two stay whole
    assert "FILE0" not in last                           # the oldest is cleared...
    assert "read_file result for f0.txt cleared" in last  # ...with a note naming it
    assert any(e.type == "tool_results_cleared" for e in result.events)
    history = "\n".join(str(m.content) for m in result.messages)
    assert "FILE0" in history                            # the history keeps it all


def test_off_by_default_every_result_is_sent(tmp_path: Path) -> None:
    llm, result = _run(tmp_path, None)
    last = "\n".join(str(m.content) for m in llm.requests[-1])
    assert all(f"FILE{n}" in last for n in range(6))
    assert not any(e.type == "tool_results_cleared" for e in result.events)
