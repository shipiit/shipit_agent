"""The SDK's result and message fields that describe how a run ended and what each model used."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.permission_rules import rule_names_tool, sdk_tool_name
from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, query

USAGE = {"prompt_tokens": 1_000_000, "completion_tokens": 100_000, "total_tokens": 1_100_000,
         "cache_read_input_tokens": 50, "cache_creation_input_tokens": 20}


class _Scripted:
    model = "claude-sonnet-5-5"

    def __init__(self, *steps: LLMResponse) -> None:
        self.steps = list(steps)

    def complete(self, **_: Any) -> LLMResponse:
        return self.steps.pop(0) if self.steps else LLMResponse(content="done", usage=USAGE)


def _echo(text: str = "") -> str:
    """Echo the text."""
    return text


def _call() -> LLMResponse:
    return LLMResponse(content="", tool_calls=[ToolCall(name="echo", arguments={"text": "x"}, id="c1")], usage=USAGE)


def _collect(**options: Any) -> list[Any]:
    options.setdefault("tools", [FunctionTool.from_callable(_echo, name="echo")])

    async def run() -> list[Any]:
        return [message async for message in query(prompt="go", options=AgentOptions(**options))]

    return asyncio.run(run())


def test_the_result_breaks_usage_and_cost_down_by_model() -> None:
    result = _collect(llm=_Scripted())[-1]
    assert isinstance(result, ResultMessage)
    usage = result.model_usage["claude-sonnet-5-5"]
    assert (usage["inputTokens"], usage["outputTokens"]) == (1_000_000, 100_000)
    assert (usage["cacheReadInputTokens"], usage["cacheCreationInputTokens"]) == (50, 20)
    # $2 per million in, $10 per million out, plus the cache tokens.
    assert usage["costUSD"] == pytest.approx(3.0, abs=0.001)
    assert result.terminal_reason == "completed" and result.uuid


def test_a_run_stopped_by_a_limit_says_which() -> None:
    result = _collect(llm=_Scripted(*[_call() for _ in range(5)]), allowed_tools=["echo"], max_turns=2)[-1]
    assert (result.subtype, result.terminal_reason) == ("error_max_turns", "max_turns")
    budget = _collect(llm=_Scripted(*[_call() for _ in range(5)]), allowed_tools=["echo"], max_budget_usd=0.5)[-1]
    assert (budget.subtype, budget.terminal_reason) == ("error_max_budget_usd", "max_budget_usd")


def test_a_run_that_raises_ends_with_an_error_reason_and_no_model_usage() -> None:
    class _Down:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            raise ValueError("boom")

    result = _collect(llm=_Down())[-1]
    assert result.is_error and result.terminal_reason == "error" and result.model_usage is None


def test_a_model_without_prices_still_reports_its_tokens() -> None:
    class _Unknown(_Scripted):
        model = "my-local-model"

    usage = _collect(llm=_Unknown())[-1].model_usage["my-local-model"]
    assert usage["inputTokens"] == 1_000_000 and usage["costUSD"] == 0.0


def test_the_blocks_of_one_response_share_a_message_id() -> None:
    messages = _collect(llm=_Scripted(_call()), allowed_tools=["echo"])
    ids = [m.message_id for m in messages if isinstance(m, AssistantMessage)]
    assert len(ids) == 2 and all(ids) and ids[0] != ids[1]


@pytest.mark.parametrize(
    ("sdk", "shipit"),
    [("ToolSearch", "tool_search"), ("ExitPlanMode", "present_plan"), ("Read", "read_file"), ("Nope", None)],
)
def test_sdk_tool_names_stand_for_shipit_tools(sdk: str, shipit: str | None) -> None:
    assert sdk_tool_name(sdk) == shipit
    if shipit:
        assert rule_names_tool(sdk, shipit)
