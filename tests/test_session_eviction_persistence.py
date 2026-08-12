"""Eviction is a per-request view — the session store keeps originals.

Turn N evicts prior turns' tool payloads from what the MODEL sees, but the
persisted session must keep the full transcript: replay, audit, and every
later turn re-derive their own view from the originals.
"""

from __future__ import annotations

import asyncio

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.stores import InMemorySessionStore
from shipit_agent.tools.base import ToolOutput

BIG = "x" * 5_000  # comfortably above the eviction threshold


class BigTool:
    name = "big_tool"
    description = "Returns a large payload."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def run(self, context, **kwargs) -> ToolOutput:
        return ToolOutput(text=BIG, metadata={})


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)
        self.seen_messages: list[list] = []

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.seen_messages.append(list(messages))
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


def _turn(store, session_id, script):
    runtime = AgentRuntime(
        llm=ScriptedLLM(script),
        prompt="You are helpful.",
        tools=[BigTool()],
        session_store=store,
        session_id=session_id,
        max_iterations=3,
        max_tool_output_chars=0,  # don't truncate; we want the raw payload
    )
    return runtime.run("do the thing")


def test_saved_session_keeps_full_tool_payloads_across_turns():
    store = InMemorySessionStore()
    sid = "sess-1"

    _turn(store, sid, [("fetching", [("big_tool", {})]), ("done turn 1", [])])
    saved_1 = store.load(sid).messages
    assert any(BIG in (m.content or "") for m in saved_1), "turn 1 payload saved whole"

    # Turn 2 evicts turn 1's payload from the REQUEST...
    llm2_script = [("done turn 2", [])]
    runtime2 = AgentRuntime(
        llm=ScriptedLLM(llm2_script),
        prompt="You are helpful.",
        tools=[BigTool()],
        session_store=store,
        session_id=sid,
        max_iterations=3,
    )
    _, response2 = runtime2.run("follow up")
    request_messages = runtime2.llm.seen_messages[0]
    assert not any(BIG in (m.content or "") for m in request_messages), (
        "the model-visible request should carry the evicted stub, not 5k of payload"
    )

    # ...but the SAVED session still holds the original.
    saved_2 = store.load(sid).messages
    assert any(BIG in (m.content or "") for m in saved_2), (
        "eviction must never be persisted — turn 2 destroyed turn 1's payload"
    )
    assert response2.content == "done turn 2"


def test_async_saved_session_keeps_full_tool_payloads():
    store = InMemorySessionStore()
    sid = "sess-async"

    async def go():
        r1 = AsyncAgentRuntime(
            llm=ScriptedLLM([("fetching", [("big_tool", {})]), ("done 1", [])]),
            prompt="You are helpful.",
            tools=[BigTool()],
            session_store=store,
            session_id=sid,
            max_iterations=3,
            max_tool_output_chars=0,
        )
        await r1.run("do the thing")
        r2 = AsyncAgentRuntime(
            llm=ScriptedLLM([("done 2", [])]),
            prompt="You are helpful.",
            tools=[BigTool()],
            session_store=store,
            session_id=sid,
            max_iterations=3,
        )
        await r2.run("follow up")

    asyncio.run(go())
    saved = store.load(sid).messages
    assert any(BIG in (m.content or "") for m in saved)
