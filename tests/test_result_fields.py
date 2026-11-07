"""The fields the Claude Agent SDK's ResultMessage carries, on AgentResult.

num_turns, duration_ms, duration_api_ms, total_cost_usd, usage,
permission_denials, stop_reason and structured_output.
"""

from __future__ import annotations

import time
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import AgentResult, ToolCall
from shipit_agent.llms.base import LLMResponse

USAGE = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}


class _Scripted:
    model = "claude-sonnet-5-5"

    def __init__(self, *steps: LLMResponse, pause: float = 0.0) -> None:
        self.steps = list(steps)
        self.pause = pause

    def complete(self, **_: Any) -> LLMResponse:
        if self.pause:
            time.sleep(self.pause)
        return self.steps.pop(0) if self.steps else LLMResponse(content="done")


def _call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(
        content="", tool_calls=[ToolCall(name=name, arguments=arguments, id=f"{name}-1")], usage=USAGE
    )


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


ECHO = FunctionTool.from_callable(_echo, name="echo")


def test_num_turns_counts_model_steps() -> None:
    result = Agent(llm=_Scripted(_call("echo", text="x")), tools=[ECHO]).run("go")
    assert result.num_turns == 2


def test_durations_are_whole_milliseconds_and_api_time_is_measured() -> None:
    llm = _Scripted(_call("echo"), LLMResponse(content="done"), pause=0.03)
    result = Agent(llm=llm, tools=[ECHO]).run("go")
    assert isinstance(result.duration_ms, int) and isinstance(result.duration_api_ms, int)
    assert result.duration_api_ms >= 50
    assert result.duration_ms >= result.duration_api_ms


def test_total_cost_and_usage_come_from_the_run() -> None:
    llm = _Scripted(_call("echo"), LLMResponse(content="done", usage=USAGE))
    result = Agent(llm=llm, tools=[ECHO]).run("go")
    assert result.total_cost_usd is not None and result.total_cost_usd > 0
    assert result.usage["total_tokens"] == 2200


def test_denied_calls_are_listed_with_their_input() -> None:
    llm = _Scripted(_call("echo", text="secret-plan"))
    result = Agent(llm=llm, tools=[ECHO], permissions={"deny": ["echo"]}).run("go")
    assert result.permission_denials == [
        {"tool_name": "echo", "tool_use_id": "echo-1", "tool_input": {"text": "secret-plan"}}
    ]


def test_a_clean_run_has_no_denials() -> None:
    result = Agent(llm=_Scripted(_call("echo")), tools=[ECHO]).run("go")
    assert result.permission_denials == []


def test_stop_reason_is_the_last_responses_finish_reason() -> None:
    llm = _Scripted(LLMResponse(content="hi", metadata={"finish_reason": "end_turn"}))
    assert Agent(llm=llm).run("go").stop_reason == "end_turn"


def test_structured_output_is_the_parsed_answer() -> None:
    llm = _Scripted(LLMResponse(content='{"title": "Dune", "rating": 9.5}'))
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "rating": {"type": "number"}},
        "required": ["title", "rating"],
    }
    result = Agent(llm=llm).run("go", output_schema=schema)
    assert result.structured_output == {"title": "Dune", "rating": 9.5}


def test_a_result_built_by_hand_has_safe_empty_values() -> None:
    result = AgentResult(output="x")
    assert result.num_turns == 0
    assert result.duration_ms == 0 and result.duration_api_ms == 0
    assert result.total_cost_usd is None
    assert result.usage == {}
    assert result.permission_denials == []
    assert result.stop_reason is None
    assert result.structured_output is None


def test_denials_do_not_carry_into_the_next_run() -> None:
    llm = _Scripted(_call("echo", text="a"), LLMResponse(content="done"), LLMResponse(content="again"))
    agent = Agent(llm=llm, tools=[ECHO], permissions={"deny": ["echo"]})
    assert len(agent.run("one").permission_denials) == 1
    assert agent.run("two").permission_denials == []


def test_a_denied_calls_long_input_is_shortened_in_the_summary() -> None:
    # Varied text: a long run of one character is refused earlier, as degenerate output.
    long_text = " ".join(f"line {i}" for i in range(700))
    llm = _Scripted(_call("echo", text=long_text))
    result = Agent(llm=llm, tools=[ECHO], permissions={"deny": ["echo"]}).run("go")
    text = result.permission_denials[0]["tool_input"]["text"]
    assert len(text) < 600 and text.startswith(long_text[:500]) and f"{len(long_text)} chars" in text
