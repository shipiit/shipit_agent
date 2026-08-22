from __future__ import annotations

import asyncio

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolOutput


class RecordingTool:
    name = "search"
    description = "Search a corpus"
    prompt_instructions = ""

    def __init__(self) -> None:
        self.calls: list[dict] = []

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

    def run(self, context, **kwargs):
        self.calls.append(kwargs)
        return ToolOutput(text="result")


class ScriptedLLM:
    model = "test-model"

    def __init__(self, arguments):
        self.arguments = arguments
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[ToolCall(name="search", arguments=self.arguments)]
            )
        return LLMResponse(content="Recovered cleanly.")


def _repeated_text() -> str:
    return " ".join(["expand this search plan repeatedly"] * 40)


def test_repetitive_structured_argument_never_reaches_the_tool():
    tool = RecordingTool()
    result = Agent(
        llm=ScriptedLLM({"query": _repeated_text()}),
        tools=[tool],
        auto_use_skills=False,
        max_iterations=3,
    ).run("search for Akira")

    assert result.output == "Recovered cleanly."
    assert tool.calls == []
    rejected = [event for event in result.events if event.type == "tool_arguments_rejected"]
    assert len(rejected) == 1


def test_repetition_is_found_inside_nested_argument_values():
    tool = RecordingTool()
    result = Agent(
        llm=ScriptedLLM({"query": {"nested": [_repeated_text()]}}),
        tools=[tool],
        auto_use_skills=False,
        max_iterations=3,
    ).run("search")

    assert result.output == "Recovered cleanly."
    assert tool.calls == []


def test_configured_argument_budget_rejects_oversized_call():
    tool = RecordingTool()
    result = Agent(
        llm=ScriptedLLM({"query": "unique enough content " * 20}),
        tools=[tool],
        auto_use_skills=False,
        max_tool_argument_chars=128,
        max_iterations=3,
    ).run("search")

    assert result.output == "Recovered cleanly."
    assert tool.calls == []


def test_normal_arguments_are_unchanged_and_execute():
    tool = RecordingTool()
    result = Agent(
        llm=ScriptedLLM({"query": "Akira ransomware"}),
        tools=[tool],
        auto_use_skills=False,
        max_iterations=3,
    ).run("search for Akira")

    assert result.output == "Recovered cleanly."
    assert tool.calls == [{"query": "Akira ransomware"}]


def test_async_runtime_has_the_same_argument_gate():
    tool = RecordingTool()
    result = asyncio.run(
        Agent(
            llm=ScriptedLLM({"query": _repeated_text()}),
            tools=[tool],
            auto_use_skills=False,
            max_iterations=3,
        ).arun("search for Akira")
    )

    assert result.output == "Recovered cleanly."
    assert tool.calls == []
