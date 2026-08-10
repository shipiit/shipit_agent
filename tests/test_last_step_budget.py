"""The final step cannot act, so it should not be sold the means to act.

A tool call emitted on the last iteration has no iteration left to run in:
the run ends with the model having announced work instead of doing it, and
the user gets no answer. Withholding the schemas there forces the answer.

It is also the single largest fixed saving available. Every tool's full JSON
schema is re-sent on every step, and the last step carries the longest
conversation — so the schemas are dropped from precisely the most expensive
request of the run.

What must NOT change: a run that had one step to begin with still gets its
tools, and every earlier step is untouched.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class _Recorder:
    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = script
        self.calls = 0
        self.tools_seen: list[list[Any]] = []

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.tools_seen.append(list(tools or []))
        self.calls += 1
        return self.script[min(self.calls - 1, len(self.script) - 1)]


def _echo(query: str) -> str:
    """Search the echo feed."""
    return f"results for {query}"


def _agent(llm, **kw) -> Agent:
    return Agent(
        llm=llm,
        tools=[FunctionTool.from_callable(_echo, name="search_echo")],
        auto_use_skills=False,
        **kw,
    )


class TestTheLastStep:
    def test_the_schemas_are_withheld(self) -> None:
        call = ToolCall(name="search_echo", arguments={"query": "q"})
        llm = _Recorder([LLMResponse(tool_calls=[call])])
        _agent(llm, max_iterations=3).run("go")
        assert llm.tools_seen[-1] == []

    def test_every_step_that_can_act_still_has_them(self) -> None:
        """Steps 1..n-1 are unaffected. Only the ones that cannot act lose
        the schemas — the final loop step, and the synthesis call after it."""
        call = ToolCall(name="search_echo", arguments={"query": "q"})
        llm = _Recorder([LLMResponse(tool_calls=[call])])
        _agent(llm, max_iterations=3).run("go")
        assert all(seen for seen in llm.tools_seen[:2])
        assert all(not seen for seen in llm.tools_seen[2:])

    def test_a_run_that_finishes_early_never_loses_them(self) -> None:
        """The saving applies to the step that cannot act, not to a short run."""
        llm = _Recorder([LLMResponse(content="done")])
        _agent(llm, max_iterations=5).run("go")
        assert llm.calls == 1 and llm.tools_seen[0]


class TestCapabilityIsNotCompromised:
    def test_a_single_step_agent_still_gets_its_tools(self) -> None:
        """Dropping schemas when there is only one step would mean the tool
        could never be called at all."""
        call = ToolCall(name="search_echo", arguments={"query": "q"})
        llm = _Recorder([LLMResponse(tool_calls=[call])])
        _agent(llm, max_iterations=1).run("go")
        assert llm.tools_seen[0]

    def test_the_tool_still_runs_when_called_on_an_earlier_step(self) -> None:
        call = ToolCall(name="search_echo", arguments={"query": "qilin"})
        llm = _Recorder([
            LLMResponse(tool_calls=[call]),
            LLMResponse(content="done"),
        ])
        result = _agent(llm, max_iterations=4).run("go")
        assert result.output == "done"
        assert any(
            e.type == "tool_completed" and e.payload["tool"] == "search_echo"
            for e in result.events
        )
