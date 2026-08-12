from __future__ import annotations

import asyncio

from shipit_agent import Agent
from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolOutput


class RepeatingLLM:
    model = "gpt-4o"

    def __init__(self, repeats: int = 3) -> None:
        self.repeats = repeats
        self.calls = 0

    def complete(self, *, messages, tools=None, **kwargs):
        self.calls += 1
        if self.calls <= self.repeats:
            return LLMResponse(
                tool_calls=[ToolCall(name="fragile", arguments={"value": "bad"})]
            )
        return LLMResponse(content="Stopped retrying the broken call.")


class FragileTool:
    name = "fragile"
    description = "Always reports a recoverable execution failure."
    prompt_instructions = ""

    def __init__(self) -> None:
        self.calls = 0

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }

    def run(self, context, **kwargs):
        self.calls += 1
        return ToolOutput(
            text="invalid value",
            metadata={"error": "invalid_argument", "argument": "value"},
        )


def test_sync_runtime_blocks_third_identical_failed_call() -> None:
    llm = RepeatingLLM()
    tool = FragileTool()
    runtime = AgentRuntime(
        llm=llm,
        prompt="Be precise.",
        tools=[tool],
        max_iterations=4,
        repeated_tool_failure_limit=2,
    )

    state, response = runtime.run("Try the fragile operation")

    assert response.content == "Stopped retrying the broken call."
    assert tool.calls == 2
    blocked = [
        event
        for event in state.events
        if event.payload.get("error") == "repeated_failure_blocked"
    ]
    assert len(blocked) == 1


def test_async_runtime_has_the_same_failure_circuit_breaker() -> None:
    llm = RepeatingLLM()
    tool = FragileTool()
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="Be precise.",
        tools=[tool],
        max_iterations=4,
        repeated_tool_failure_limit=2,
    )

    state, response = asyncio.run(runtime.run("Try the fragile operation"))

    assert response.content == "Stopped retrying the broken call."
    assert tool.calls == 2
    assert any(
        event.payload.get("error") == "repeated_failure_blocked"
        for event in state.events
    )


def test_plain_agent_compacts_from_model_limits_by_default() -> None:
    agent = Agent(llm=RepeatingLLM(repeats=0), auto_use_skills=False)

    assert agent._effective_context_window_tokens() == 128_000 - 16_384


def test_automatic_compaction_can_be_disabled_or_overridden() -> None:
    disabled = Agent(
        llm=RepeatingLLM(repeats=0),
        auto_use_skills=False,
        auto_compact=False,
    )
    explicit = Agent(
        llm=RepeatingLLM(repeats=0),
        auto_use_skills=False,
        context_window_tokens=42_000,
    )

    assert disabled._effective_context_window_tokens() == 0
    assert explicit._effective_context_window_tokens() == 42_000
