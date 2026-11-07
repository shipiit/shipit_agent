"""A model repeating one call that keeps returning the same result is stopped.

With no step limit, a model that calls the same tool with the same arguments
forever, getting the same answer each time, would never finish. After three
identical steps the tool is withheld, as repeated read-only calls already
are; a call whose result changes (polling a build) is never affected.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse


class _KeepsCalling:
    def __init__(self, tool: str, *, stop_after: int | None = None) -> None:
        self.tool = tool
        self.stop_after = stop_after
        self.calls = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.stop_after is not None and self.calls > self.stop_after:
            return LLMResponse(content="Build finished.")
        return LLMResponse(
            content="", tool_calls=[ToolCall(name=self.tool, arguments={"job": "42"})]
        )


def _deploy(job: str = "") -> str:
    """Deploy a job (changes things, so never deduplicated as read-only)."""
    return f"deploy {job} queued"


def test_the_same_call_and_result_three_times_withholds_the_tool() -> None:
    llm = _KeepsCalling("deploy")
    agent = Agent(llm=llm, tools=[FunctionTool.from_callable(_deploy, name="deploy")])

    result = agent.run("go")

    ran = [e for e in result.events if e.type == "tool_called"]
    assert len(ran) == 3
    assert llm.calls <= 6
    assert result.output.strip()
    withheld = [e for e in result.events if e.type == "tool_withheld"]
    assert withheld and withheld[0].payload["tools"] == ["deploy"]


def test_a_call_whose_result_changes_is_left_alone() -> None:
    progress = iter(f"{n}% built" for n in range(0, 100, 10))

    def status(job: str = "") -> str:
        """Report build progress."""
        return next(progress)

    llm = _KeepsCalling("status", stop_after=8)
    agent = Agent(llm=llm, tools=[FunctionTool.from_callable(status, name="status")])

    result = agent.run("go")

    assert result.output == "Build finished."
    assert not [e for e in result.events if e.type == "tool_withheld"]
