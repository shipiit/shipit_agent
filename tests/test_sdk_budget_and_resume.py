"""``task_budget`` (a token cap for one run) and ``resume_session_at`` (resume from an earlier point)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, ResultMessage, build_agent, get_session_messages, list_sessions, query
from shipit_agent.stores.session import InMemorySessionStore

USAGE = {"prompt_tokens": 600, "completion_tokens": 400, "total_tokens": 1000}


def _echo(text: str = "") -> str:
    """Echo the text."""
    return text


class _Loops:
    model = "claude-sonnet-5-5"

    def complete(self, **_: Any) -> LLMResponse:
        return LLMResponse(content="", tool_calls=[ToolCall(name="echo", arguments={"text": "x"})], usage=USAGE)


class _Talks:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.users: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.users.append([str(m.content) for m in messages if m.role == "user"])
        return LLMResponse(content=f"reply {len(self.users)}", usage=USAGE)


def _run(prompt: str, **options: Any) -> ResultMessage:
    async def go() -> list[Any]:
        return [m async for m in query(prompt=prompt, options=AgentOptions(**options))]

    return asyncio.run(go())[-1]


def test_a_task_budget_stops_the_run_at_its_token_total() -> None:
    tools = [FunctionTool.from_callable(_echo, name="echo")]
    result = _run("go", llm=_Loops(), tools=tools, allowed_tools=["echo"], task_budget={"total": 2500}, max_turns=50)
    assert (result.subtype, result.terminal_reason) == ("error_max_budget_tokens", "max_budget_tokens")
    assert result.num_turns == 3


@pytest.mark.parametrize("budget", [{"total": 0}, {"total": -5}, {"total": "many"}, {"total": True}, {}, {"tokens": 5}, 100])
def test_a_task_budget_that_is_not_a_positive_total_is_refused(budget: Any) -> None:
    with pytest.raises(ValueError, match="task_budget"):
        build_agent(AgentOptions(llm=_Talks(), tools=[], task_budget=budget))


def test_no_task_budget_leaves_the_run_uncapped() -> None:
    assert build_agent(AgentOptions(llm=_Talks(), tools=[])).max_task_tokens is None


def _two_turns() -> tuple[InMemorySessionStore, str]:
    store = InMemorySessionStore()
    _run("First question.", llm=_Talks(), tools=[], session_store=store, session_id="s-1")
    _run("Second question.", llm=_Talks(), tools=[], session_store=store, resume="s-1")
    return store, "s-1"


def test_resuming_at_a_message_continues_from_there_in_a_copy() -> None:
    store, session_id = _two_turns()
    before = [m.uuid for m in get_session_messages(store, session_id)]
    first_reply = get_session_messages(store, session_id)[1].uuid
    llm = _Talks()
    result = _run("Different second question.", llm=llm, tools=[], session_store=store,
                  resume=session_id, resume_session_at=first_reply)
    sent = "\n".join(llm.users[0])
    assert "First question." in sent and "Different second question." in sent
    assert "Second question." not in sent.replace("Different second question.", "")
    assert result.session_id != session_id
    # The session resumed from is left as it was.
    assert [m.uuid for m in get_session_messages(store, session_id)] == before
    assert len(list_sessions(store)) == 2


def test_resume_session_at_needs_a_session_and_a_message_of_it() -> None:
    store, session_id = _two_turns()
    with pytest.raises(ValueError, match="resume_session_at"):
        build_agent(AgentOptions(llm=_Talks(), tools=[], session_store=store, resume_session_at=f"{session_id}:0"))
    with pytest.raises(ValueError, match="not a message"):
        build_agent(AgentOptions(llm=_Talks(), tools=[], session_store=store, resume=session_id, resume_session_at="other:0"))
    with pytest.raises(ValueError, match="not a message"):
        build_agent(AgentOptions(llm=_Talks(), tools=[], session_store=store, resume=session_id, resume_session_at=f"{session_id}:99"))


class _UsesTool:
    """Calls echo once, then answers; later runs just answer and record what they were sent."""

    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.sent: list[list[Any]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.sent.append(list(messages))
        if len(self.sent) == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(name="echo", arguments={"text": "x"}, id="c1")], usage=USAGE)
        return LLMResponse(content="done", usage=USAGE)


def test_resuming_at_a_tool_call_keeps_that_calls_result() -> None:
    tools = [FunctionTool.from_callable(_echo, name="echo")]
    store = InMemorySessionStore()
    _run("Echo x.", llm=_UsesTool(), tools=tools, allowed_tools=["echo"], session_store=store, session_id="s-1")
    saved = get_session_messages(store, "s-1")
    calling = next(m for m in saved if m.type == "assistant")
    probe = _UsesTool()
    probe.sent.append([])  # so it answers straight away
    result = _run("And then?", llm=probe, tools=tools, session_store=store, resume="s-1", resume_session_at=calling.uuid)
    assert result.subtype == "success"
    sent = probe.sent[-1]
    call_ids = [c["id"] for m in sent if m.role == "assistant" for c in m.metadata.get("tool_calls", [])]
    answered = [m.tool_call_id for m in sent if m.role == "tool"]
    # A tool call sent without its result is refused by every provider.
    assert call_ids == ["c1"] and answered == ["c1"]
    assert not any(m.role == "assistant" and m.content == "done" for m in sent)
