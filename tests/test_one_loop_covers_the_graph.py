"""What the retired v2 graph loop guaranteed, now pinned on the one loop.

The graph loop's tests drove a stand-in agent through a bridge. When the
graph was retired, each behaviour it guaranteed was ported here, run on the
real ``Agent``. Behaviours already pinned elsewhere are named, not repeated:

- skill catalog in the prompt, bodies on demand: test_skills_on_demand.py
- a skill loaded mid-run: test_skills_on_demand.py
- the step limit: test_step_limit_and_budget.py
- cancellation between steps: test_core_runtime_fixes.py and others
- a denied tool needing approval: test_shell_gate.py, test_permission_order.py
- deferred tools and tool_search: test_deferred_tools.py
- MCP server instructions in the prompt: test_mcp_server_instructions.py
- compaction events: test_compaction_*.py
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import Message, ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.base import ToolOutput, ToolOutputChunk


class _Scripted:
    """Replays responses; records what each call was sent."""

    model = "claude-sonnet-5-5"

    def __init__(self, *steps: LLMResponse) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, messages: Any, tools: Any = None, **_: Any) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        self.calls.append(
            {
                "system": system,
                "tools": json.dumps(tools or [], sort_keys=True),
                "messages": list(messages),
            }
        )
        return self.steps.pop(0) if self.steps else LLMResponse(content="done")


def _call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(name=name, arguments=arguments, id=f"{name}-1")],
    )


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


ECHO = FunctionTool.from_callable(_echo, name="echo")


# -- the loop ---------------------------------------------------------------


def test_a_plain_answer_ends_the_run_in_one_step() -> None:
    llm = _Scripted(LLMResponse(content="hello"))
    result = Agent(llm=llm).run("hi")
    assert result.output == "hello"
    assert len(llm.calls) == 1


def test_a_tool_call_runs_and_the_loop_continues() -> None:
    llm = _Scripted(_call("echo", text="x"), LLMResponse(content="done"))
    result = Agent(llm=llm, tools=[ECHO]).run("go")
    assert [r.output for r in result.tool_results] == ["echo:x"]
    assert result.output == "done"
    assert len(llm.calls) == 2


def test_history_is_paired_after_a_tool_round_trip() -> None:
    llm = _Scripted(_call("echo", text="x"), LLMResponse(content="done"))
    Agent(llm=llm, tools=[ECHO]).run("go")
    second = llm.calls[1]["messages"]
    assistant = next(
        m for m in second if m.role == "assistant" and m.metadata.get("tool_calls")
    )
    tool = next(m for m in second if m.role == "tool")
    call_ids = [c.get("id") for c in assistant.metadata["tool_calls"]]
    assert tool.tool_call_id in call_ids


def test_a_failing_tool_does_not_end_the_run() -> None:
    def broken(text: str = "") -> str:
        """Always fails."""
        raise ValueError("nope")

    llm = _Scripted(_call("broken"), LLMResponse(content="recovered"))
    result = Agent(
        llm=llm, tools=[FunctionTool.from_callable(broken, name="broken")]
    ).run("go")
    assert result.tool_results[0].is_error
    assert result.output == "recovered"


def test_an_unknown_tool_is_a_recoverable_result() -> None:
    llm = _Scripted(_call("no_such_tool"), LLMResponse(content="ok"))
    result = Agent(llm=llm, tools=[ECHO]).run("go")
    tool_messages = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert "not registered" in tool_messages[0].content
    assert result.output == "ok"


def test_the_prefix_is_stable_across_steps() -> None:
    llm = _Scripted(
        _call("echo", text="a"), _call("echo", text="b"), LLMResponse(content="done")
    )
    Agent(llm=llm, tools=[ECHO]).run("go")
    assert len({c["system"] for c in llm.calls}) == 1
    assert len({c["tools"] for c in llm.calls}) == 1


def test_tool_output_streams_live_with_its_call_id() -> None:
    def ticker() -> Any:
        """Emit three chunks."""
        for index in range(3):
            yield ToolOutputChunk(f"x-{index}")

    llm = _Scripted(_call("ticker"), LLMResponse(content="done"))
    events = list(
        Agent(
            llm=llm, tools=[FunctionTool.from_callable(ticker, name="ticker")]
        ).stream("go")
    )
    deltas = [e for e in events if e.type == "tool_output_delta"]
    assert [d.payload["chunk"] for d in deltas] == ["x-0", "x-1", "x-2"]
    assert all(d.payload["tool_call_id"] for d in deltas)


def test_a_tools_own_metadata_reaches_the_result() -> None:
    class Tagged:
        name = "tagged"
        description = "tagged"
        prompt_instructions = ""

        def schema(self) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": "tagged",
                    "description": "t",
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        def run(self, context: Any, **_: Any) -> ToolOutput:
            return ToolOutput(text="ok", metadata={"source": "unit"})

    llm = _Scripted(_call("tagged"), LLMResponse(content="done"))
    result = Agent(llm=llm, tools=[Tagged()]).run("go")
    assert result.tool_results[0].metadata["source"] == "unit"


def test_a_tool_reporting_its_own_error_is_recorded_as_an_error() -> None:
    class Reports:
        name = "reports"
        description = "reports"
        prompt_instructions = ""

        def schema(self) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": "reports",
                    "description": "r",
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        def run(self, context: Any, **_: Any) -> ToolOutput:
            return ToolOutput.error("quota exceeded", error="quota")

    llm = _Scripted(_call("reports"), LLMResponse(content="done"))
    result = Agent(llm=llm, tools=[Reports()]).run("go")
    assert result.tool_results[0].is_error


def test_usage_is_recorded_for_every_model_call() -> None:
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    llm = _Scripted(
        LLMResponse(
            content="",
            tool_calls=[ToolCall(name="echo", arguments={}, id="e")],
            usage=usage,
        ),
        LLMResponse(content="done", usage=usage),
    )
    result = Agent(llm=llm, tools=[ECHO]).run("go")
    assert result.metadata["run_summary"]["usage"]["total_tokens"] == 24


# -- the *_v2 entry points ----------------------------------------------------


def test_run_v2_is_run() -> None:
    result = Agent(llm=_Scripted(LLMResponse(content="ok"))).run_v2("hi")
    assert result.output == "ok"


def test_stream_v2_ends_with_the_run_completing() -> None:
    events = list(Agent(llm=_Scripted(LLMResponse(content="ok"))).stream_v2("hi"))
    assert events[-1].type == "run_completed"


def test_packets_v2_terminate_last_and_carry_call_ids() -> None:
    llm = _Scripted(_call("echo", text="x"), LLMResponse(content="done"))
    packets = list(Agent(llm=llm, tools=[ECHO]).packets_v2("go"))
    assert packets[-1].is_terminal
    assert any(p.tool_call_id for p in packets if p.tool == "echo")


def test_two_runs_do_not_leak_into_each_other() -> None:
    agent = Agent(
        llm=_Scripted(LLMResponse(content="first"), LLMResponse(content="second"))
    )
    assert agent.run_v2("a").output == "first"
    assert agent.run_v2("b").output == "second"


def test_history_is_carried_when_the_agent_has_it() -> None:
    llm = _Scripted(LLMResponse(content="ok"))
    Agent(llm=llm, history=[Message(role="user", content="earlier")]).run_v2("now")
    texts = [m.content for m in llm.calls[0]["messages"] if m.role == "user"]
    # The loop labels user turns ("[User turn 1]"); the content is carried.
    assert "earlier" in str(texts[0])
    assert "now" in str(texts[-1])


# -- preflight ----------------------------------------------------------------


def test_preflight_reports_the_model_and_prefix() -> None:
    report = Agent(llm=_Scripted(), tools=[ECHO]).preflight()
    assert report["model"] == "claude-sonnet-5-5"
    assert report["context_window"] == 1_000_000
    assert report["prefix_tokens"] > 0
    assert report["tools_bound"] >= 1


def test_preflight_costs_no_model_call() -> None:
    llm = _Scripted()
    Agent(llm=llm).preflight()
    assert llm.calls == []


def test_preflight_names_a_dead_mcp_server() -> None:
    class Dead:
        name = "jira"
        instructions = ""

        def discover_tools(self) -> list[Any]:
            raise RuntimeError("would not start")

    report = Agent(llm=_Scripted(), mcps=[Dead()]).preflight()
    assert "jira" in report["mcp"]["failed"]
    assert any("jira" in warning for warning in report["warnings"])


def test_preflight_flags_a_prompt_that_eats_the_budget() -> None:
    llm = _Scripted()
    llm.model = "totally-unknown-model"
    report = Agent(llm=llm, prompt="rule. " * 120_000).preflight()
    assert any("input budget" in warning for warning in report["warnings"])
    assert any("No context window" in warning for warning in report["warnings"])


@pytest.mark.parametrize("configured", [{}, {"code_mode": True}])
def test_nothing_is_missing_from_the_one_loop(configured: dict[str, Any]) -> None:
    assert Agent(llm=_Scripted(), **configured).upgrade_report() == {}
