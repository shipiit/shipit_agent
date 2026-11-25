"""A sub-agent's work in the SDK stream, attributed to the tool call that started it."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import SubAgentTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentOptions,
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from shipit_agent.tools.base import ToolOutput


class _Tool:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.prompt_instructions = name, name, ""

    def schema(self) -> dict[str, Any]:
        return {"function": {"name": self.name, "parameters": {"properties": {"path": {"type": "string"}}}}}

    def run(self, context: Any, **kwargs: Any) -> ToolOutput:
        return ToolOutput(text=f"{self.name} ok")


class _Child:
    """Reads a file, then reports, separately for each brief."""

    model = "child-model"

    def __init__(self) -> None:
        self.turns: dict[str, int] = {}

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        brief = " ".join(str(m.content) for m in messages if m.role == "user")
        key = "auth" if "auth" in brief else "billing"
        self.turns[key] = self.turns.get(key, 0) + 1
        if self.turns[key] == 1:
            return LLMResponse(content=f"Reading {key}.", reasoning_content="think",
                               tool_calls=[ToolCall(name="read_file", arguments={"path": f"{key}.py"}, id=f"{key}-read")],
                               usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        return LLMResponse(content=f"{key} reviewed", usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25})


class _Parent:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="Delegating.", tool_calls=[
                ToolCall(name="sub_agent", arguments={"task": "review auth"}, id="p-auth"),
                ToolCall(name="sub_agent", arguments={"task": "review billing"}, id="p-billing"),
            ])
        return LLMResponse(content="Both reviewed.")


def _run(**options: Any) -> list[Any]:
    tools = [SubAgentTool(llm=_Child()), _Tool("read_file")]
    opts = AgentOptions(llm=_Parent(), tools=tools, allowed_tools=["sub_agent", "read_file"], **options)

    async def go() -> list[Any]:
        return [message async for message in query(prompt="Review both.", options=opts)]

    return asyncio.run(go())


def _by_parent(messages: list[Any], kind: type) -> dict[str | None, list[Any]]:
    grouped: dict[str | None, list[Any]] = {}
    for message in messages:
        if isinstance(message, kind):
            grouped.setdefault(message.parent_tool_use_id, []).append(message)
    return grouped


def test_each_childs_calls_and_results_name_the_call_that_started_it() -> None:
    messages = _run()
    assistant = _by_parent(messages, AssistantMessage)
    results = _by_parent(messages, UserMessage)
    for key in ("auth", "billing"):
        calls = [b for m in assistant[f"p-{key}"] for b in m.content if isinstance(b, ToolUseBlock)]
        assert [(c.id, c.name, c.input) for c in calls] == [(f"{key}-read", "read_file", {"path": f"{key}.py"})]
        blocks = [b for m in results[f"p-{key}"] for b in m.content if isinstance(b, ToolResultBlock)]
        assert [(b.tool_use_id, b.content) for b in blocks] == [(f"{key}-read", "read_file ok")]
    # The parent's own messages have no parent.
    own = [b for m in assistant[None] for b in m.content if isinstance(b, ToolUseBlock)]
    assert [c.id for c in own] == ["p-auth", "p-billing"]
    assert sum(isinstance(m, ResultMessage) for m in messages) == 1 and messages[-1].result == "Both reviewed."


def test_a_childs_text_and_thinking_are_left_out_unless_forwarded() -> None:
    quiet = _by_parent(_run(), AssistantMessage)["p-auth"]
    assert not any(isinstance(b, TextBlock) for m in quiet for b in m.content)
    assert all(m.content for m in quiet)
    loud = _by_parent(_run(forward_subagent_text=True), AssistantMessage)["p-auth"]
    texts = [b.text for m in loud for b in m.content if isinstance(b, TextBlock)]
    assert texts == ["Reading auth.", "auth reviewed"]


def test_progress_is_reported_for_each_child() -> None:
    progress = [m for m in _run() if isinstance(m, SystemMessage) and m.subtype == "task_progress"]
    last = {m.data["tool_use_id"]: m.data for m in progress}
    assert set(last) == {"p-auth", "p-billing"}
    for key in ("auth", "billing"):
        data = last[f"p-{key}"]
        assert data["task_id"] == f"p-{key}" and data["description"] == f"review {key}"
        # The last report comes when the child finishes, with both responses counted.
        assert data["usage"]["tool_uses"] == 1 and data["usage"]["total_tokens"] == 40
        assert data["last_tool_name"] == "read_file" and data["usage"]["duration_ms"] >= 0


def test_a_child_never_streams_partial_events() -> None:
    messages = _run(include_partial_messages=True)
    starts = [m for m in messages if isinstance(m, StreamEvent) and m.event["type"] == "message_start"]
    assert len(starts) == 2  # the parent's two responses only
    assert all(m.parent_tool_use_id is None for m in messages if isinstance(m, StreamEvent))


@pytest.mark.parametrize("payload", [{}, {"inner_type": "assistant_message"}, {"inner_type": "something_new", "inner": {}}])
def test_odd_sub_agent_events_are_ignored(payload: dict[str, Any]) -> None:
    from shipit_agent.core.models import AgentEvent
    from shipit_agent.sdk.convert import MessageStream

    stream = MessageStream(init={"model": "m"})
    assert stream.feed(AgentEvent(type="sub_agent_event", message="", payload=payload)) == []


def test_parallel_tool_calls_each_see_their_own_call_id() -> None:
    import threading
    import time

    from shipit_agent import Agent
    from shipit_agent.core.tool_runner import CURRENT_TOOL_CALL_ID

    seen: dict[str, str | None] = {}
    both_running = threading.Barrier(2, timeout=5)

    class _Probe(_Tool):
        read_only = True

        def run(self, context: Any, **kwargs: Any) -> ToolOutput:
            both_running.wait()  # proves the two calls overlap
            time.sleep(0.01)
            seen[kwargs["path"]] = CURRENT_TOOL_CALL_ID.get()
            return ToolOutput(text="ok")

    class _Calls:
        model = "m"

        def __init__(self) -> None:
            self.turn = 0

        def complete(self, **_: Any) -> LLMResponse:
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(tool_calls=[
                    ToolCall(name="probe", arguments={"path": "a"}, id="call-a"),
                    ToolCall(name="probe", arguments={"path": "b"}, id="call-b"),
                ])
            return LLMResponse(content="done")

    Agent(llm=_Calls(), tools=[_Probe("probe")], parallel_tool_execution=True).run("go")
    assert seen == {"a": "call-a", "b": "call-b"}
    assert CURRENT_TOOL_CALL_ID.get() is None


def test_a_call_without_an_id_runs_and_sets_no_id() -> None:
    from shipit_agent.core.registry import ToolRegistry
    from shipit_agent.core.tool_runner import CURRENT_TOOL_CALL_ID, ToolRunner
    from shipit_agent.tools.base import ToolContext

    seen: list[str | None] = []

    class _Reads(_Tool):
        def run(self, context: Any, **kwargs: Any) -> ToolOutput:
            seen.append(CURRENT_TOOL_CALL_ID.get())
            return ToolOutput(text="ok")

    bare = type("Bare", (), {"name": "probe", "arguments": {}})()
    ToolRunner(ToolRegistry.build(tools=[_Reads("probe")])).run_tool_call(bare, ToolContext(prompt=""))
    assert seen == [None]
