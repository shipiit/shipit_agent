"""Deferring a tool call: pause the run, decide later, resume, as in the Claude Agent SDK."""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.hooks import AgentHooks
from shipit_agent.sdk import AgentOptions, HookMatcher, ResultMessage, query
from shipit_agent.stores.session import InMemorySessionStore


class _Model:
    """Calls refund once, then answers; records every conversation it is sent."""

    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.asked = False

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.asked:
            self.asked = True
            return LLMResponse(content="", tool_calls=[ToolCall(name="refund", arguments={"order": "A1"}, id="r1")])
        return LLMResponse(content="Refund handled.")


def _refund(order: str = "") -> str:
    """Refund an order."""
    ran.append(order)
    return f"refunded {order}"


ran: list[str] = []
REFUND = FunctionTool.from_callable(_refund, name="refund")


class _Gate:
    """A before-tool hook whose answer for refunds can change between runs."""

    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.asked = 0

    def __call__(self, name: str, arguments: dict[str, Any]) -> Any:
        if name != "refund":
            return None
        self.asked += 1
        return {"decision": self.decision, "reason": "a manager must approve refunds"}


def _agent(llm: _Model, gate: _Gate, store: InMemorySessionStore) -> Agent:
    hooks = AgentHooks()
    hooks.on_before_tool(gate)
    return Agent(llm=llm, tools=[REFUND], hooks=hooks, session_id="s-1", session_store=store)


def setup_function() -> None:
    ran.clear()


def test_a_deferred_call_pauses_the_run_and_is_saved() -> None:
    llm, store = _Model(), InMemorySessionStore()
    result = _agent(llm, _Gate("defer"), store).run("refund order A1")
    assert ran == [] and len(llm.calls) == 1
    assert result.stop_reason == "tool_deferred" and result.output.startswith("Paused: refund")
    assert result.deferred_tool_use == {"id": "r1", "name": "refund", "input": {"order": "A1"},
                                        "reason": "a manager must approve refunds"}
    assert store.load("s-1").metadata["deferred_tool_use"]["id"] == "r1"
    assert any(e.type == "tool_deferred" for e in result.events)


def test_an_approval_runs_the_call_before_the_model_continues() -> None:
    llm, store, gate = _Model(), InMemorySessionStore(), _Gate("defer")
    agent = _agent(llm, gate, store)
    agent.run("refund order A1")
    gate.decision = "allow"
    result = agent.run("approved, carry on")
    assert ran == ["A1"] and gate.asked == 2
    second = llm.calls[1]
    tool_messages = [m for m in second if m.role == "tool" and m.metadata.get("tool_call_id") == "r1"]
    assert [m.content for m in tool_messages] == ["refunded A1"]
    assert result.output == "Refund handled." and result.deferred_tool_use is None
    assert "deferred_tool_use" not in store.load("s-1").metadata


def test_a_refusal_is_recorded_in_place_of_the_call() -> None:
    llm, store, gate = _Model(), InMemorySessionStore(), _Gate("defer")
    agent = _agent(llm, gate, store)
    agent.run("refund order A1")
    gate.decision = "deny"
    agent.run("the manager said no")
    assert ran == []
    [denied] = [m for m in llm.calls[1] if m.role == "tool" and m.metadata.get("tool_call_id") == "r1"]
    assert "DENIED" in denied.content


def test_deferring_again_pauses_without_calling_the_model() -> None:
    llm, store, gate = _Model(), InMemorySessionStore(), _Gate("defer")
    agent = _agent(llm, gate, store)
    agent.run("refund order A1")
    result = agent.run("any news?")
    assert len(llm.calls) == 1 and result.stop_reason == "tool_deferred" and ran == []


def test_deny_beats_defer_and_defer_beats_ask() -> None:
    hooks = AgentHooks()
    hooks.on_before_tool(lambda *_: {"decision": "ask"})
    hooks.on_before_tool(lambda *_: {"decision": "defer"})
    assert hooks.run_before_tool("refund", {}).deferred
    hooks.on_before_tool(lambda *_: {"decision": "deny"})
    assert hooks.run_before_tool("refund", {}).denied


def test_the_sdk_reports_and_resumes_a_deferred_call() -> None:
    store = InMemorySessionStore()
    decision = {"value": "defer"}

    async def gate(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision["value"]}}

    def run(prompt: str, llm: _Model, **extra: Any) -> ResultMessage:
        async def go() -> list[Any]:
            options = AgentOptions(llm=llm, tools=[REFUND], session_store=store,
                                   hooks={"PreToolUse": [HookMatcher("refund", [gate])]}, **extra)
            return [m async for m in query(prompt=prompt, options=options)]

        return asyncio.run(go())[-1]

    llm = _Model()
    paused = run("refund order A1", llm, session_id="s-2")
    assert paused.deferred_tool_use["name"] == "refund" and paused.stop_reason == "tool_deferred"
    decision["value"] = "allow"
    resumed = run("approved", llm, resume="s-2")
    assert ran == ["A1"] and resumed.result == "Refund handled." and resumed.deferred_tool_use is None
