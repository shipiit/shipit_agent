from __future__ import annotations

import asyncio

import pytest

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall, ToolResult
from shipit_agent.runtime import AgentRuntime
from shipit_agent.session_facts import FactLedger
from shipit_agent.stores import InMemorySessionStore
from shipit_agent.tools.base import ToolOutput


class FactTool:
    name = "lookup_actor"
    description = "Look up an actor"
    prompt_instructions = ""

    def schema(self):
        return {
            "function": {
                "name": self.name,
                "parameters": {"type": "object", "properties": {}},
            }
        }

    def run(self, _context, **_kwargs):
        return ToolOutput(
            text="Akira profile",
            metadata={"facts": {"actor": "Akira", "status": "active"}},
        )


class RecordingLLM:
    model = "test"

    def __init__(self, *, call_tool: bool = False):
        self.call_tool = call_tool
        self.calls = 0
        self.messages = []

    def complete(self, *, messages, **_kwargs):
        self.messages.append(list(messages))
        self.calls += 1
        if self.call_tool and self.calls == 1:
            return LLMResponse(
                tool_calls=[ToolCall(name="lookup_actor", id="fact_call")]
            )
        return LLMResponse(content="done")


def test_ledger_accepts_only_explicit_tool_metadata() -> None:
    ledger = FactLedger()
    changed = ledger.ingest_tool_results(
        [
            ToolResult(name="prose", output="actor=guessed", tool_call_id="a"),
            ToolResult(
                name="lookup",
                output="opaque",
                tool_call_id="b",
                metadata={"facts": {"actor": "Akira"}},
            ),
        ]
    )
    assert changed == 1
    assert "actor = Akira (source: lookup/b)" in ledger.render()
    assert "guessed" not in ledger.render()


@pytest.mark.parametrize("runtime_type", ["sync", "async"])
def test_verified_facts_survive_turns_without_polluting_history(runtime_type) -> None:
    store = InMemorySessionStore()
    first_llm = RecordingLLM(call_tool=True)
    first = (
        AgentRuntime(
            llm=first_llm,
            prompt="p",
            tools=[FactTool()],
            session_store=store,
            session_id="facts",
        )
        if runtime_type == "sync"
        else AsyncAgentRuntime(
            llm=first_llm,
            prompt="p",
            tools=[FactTool()],
            session_store=store,
            session_id="facts",
        )
    )
    if runtime_type == "sync":
        first.run("find actor")
    else:
        asyncio.run(first.run("find actor"))

    saved = store.load("facts")
    assert saved is not None
    assert saved.metadata["verified_facts"][0]["source_call_id"] == "fact_call"

    second_llm = RecordingLLM()
    second = (
        AgentRuntime(
            llm=second_llm,
            prompt="p",
            session_store=store,
            session_id="facts",
        )
        if runtime_type == "sync"
        else AsyncAgentRuntime(
            llm=second_llm,
            prompt="p",
            session_store=store,
            session_id="facts",
        )
    )
    if runtime_type == "sync":
        second.run("what was the actor?")
    else:
        asyncio.run(second.run("what was the actor?"))

    supplied = [
        message
        for message in second_llm.messages[0]
        if message.metadata.get("kind") == "verified_session_facts"
    ]
    assert len(supplied) == 1
    assert "actor = Akira" in supplied[0].text

    saved_again = store.load("facts")
    assert saved_again is not None
    assert not any(
        message.metadata.get("kind") == "verified_session_facts"
        for message in saved_again.messages
    )
