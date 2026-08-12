from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool


class UnreachableTool:
    name = "remote_lookup"
    description = "Read records from a remote service."
    prompt_instructions = "Use for remote records."
    recoverable_exceptions: tuple[type[Exception], ...] = ()

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
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        self.calls += 1
        return ToolOutput(
            "connection refused by remote endpoint",
            {"error": "connection refused"},
        )


class DifferentArgumentsLLM:
    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools=None, **kwargs) -> LLMResponse:
        self.turn += 1
        if self.turn <= 2:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="remote_lookup",
                        arguments={"query": f"attempt-{self.turn}"},
                    )
                ]
            )
        return LLMResponse(content="The remote source is unavailable.")


def test_transport_breaker_blocks_changed_arguments_for_same_tool() -> None:
    tool = UnreachableTool()
    result = Agent(
        llm=DifferentArgumentsLLM(),
        tools=[tool],
        auto_use_skills=False,
        max_iterations=3,
        tool_context_mode="full",
    ).run("Look up the remote record")

    assert tool.calls == 1
    blocked = [event for event in result.events if event.type == "tool_circuit_blocked"]
    assert len(blocked) == 1
    assert blocked[0].payload["tool"] == "remote_lookup"
    completed = [event for event in result.events if event.type == "tool_completed"]
    assert completed[0].payload["metadata"]["transport_circuit_opened"] is True


def test_transport_breaker_can_be_disabled() -> None:
    tool = UnreachableTool()
    Agent(
        llm=DifferentArgumentsLLM(),
        tools=[tool],
        auto_use_skills=False,
        max_iterations=3,
        tool_context_mode="full",
        transport_circuit_breaker=False,
    ).run("Look up the remote record")

    assert tool.calls == 2


class DiscoveryThenStopLLM:
    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools=None, **kwargs) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="tool_search",
                        arguments={"query": "remote records", "detail": "name"},
                    )
                ]
            )
        if self.turn == 2:
            return LLMResponse(content="I found a remote lookup capability.")
        if self.turn == 3:
            return LLMResponse(
                tool_calls=[
                    ToolCall(name="remote_lookup", arguments={"query": "record-1"})
                ]
            )
        return LLMResponse(content="The record was retrieved.")


class WorkingRemoteTool(UnreachableTool):
    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        self.calls += 1
        return ToolOutput("record-1: ready", {"ok": True})


def test_discovery_only_answer_is_nudged_to_execute_capability() -> None:
    tool = WorkingRemoteTool()
    result = Agent(
        llm=DiscoveryThenStopLLM(),
        tools=[ToolSearchTool(), tool],
        auto_use_skills=False,
        max_iterations=4,
        tool_context_mode="full",
    ).run("Retrieve remote record-1")

    assert tool.calls == 1
    assert any(
        event.type == "tool_call_healed"
        and event.payload.get("reason") == "discovery_only"
        for event in result.events
    )


def test_tool_catalog_question_does_not_force_execution() -> None:
    tool = WorkingRemoteTool()
    llm = DiscoveryThenStopLLM()
    result = Agent(
        llm=llm,
        tools=[ToolSearchTool(), tool],
        auto_use_skills=False,
        max_iterations=4,
        tool_context_mode="full",
    ).run("Which tool can retrieve remote records?")

    assert tool.calls == 0
    assert result.output == "I found a remote lookup capability."
    assert not any(
        event.payload.get("reason") == "discovery_only" for event in result.events
    )
