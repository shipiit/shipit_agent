"""Saved sessions through ``shipit_agent.sdk``: list, read, rename, tag, fork, resume."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentOptions,
    ResultMessage,
    fork_session,
    get_session_info,
    get_session_messages,
    list_sessions,
    query,
    rename_session,
    tag_session,
)
from shipit_agent.stores.session import InMemorySessionStore


class _Model:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.users: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.users.append([str(m.content) for m in messages if m.role == "user"])
        return LLMResponse(content=f"reply {len(self.users)}")


def _run(prompt: str, **options: Any) -> ResultMessage:
    async def go() -> list[Any]:
        return [m async for m in query(prompt=prompt, options=AgentOptions(tools=[], **options))]

    return asyncio.run(go())[-1]


@pytest.fixture
def saved() -> tuple[InMemorySessionStore, str]:
    store = InMemorySessionStore()
    _run("Plan the release.", llm=_Model(), session_store=store, session_id="s-1")
    return store, "s-1"


def test_a_run_with_a_store_is_listed(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    [info] = list_sessions(store)
    assert info.session_id == session_id
    assert "Plan the release." in info.first_prompt and info.summary
    assert info.custom_title is None and info.tag is None and info.message_count >= 2


def test_messages_are_the_user_and_assistant_turns(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    messages = get_session_messages(store, session_id)
    assert [m.type for m in messages] == ["user", "assistant"]
    assert messages[0].uuid.startswith(f"{session_id}:")
    assert get_session_messages(store, session_id, offset=1, limit=1)[0].type == "assistant"
    assert get_session_messages(store, "missing") == []


def test_rename_and_tag(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    rename_session(store, session_id, "Release plan")
    tag_session(store, session_id, "q3")
    info = get_session_info(store, session_id)
    assert info is not None
    assert (info.custom_title, info.summary, info.tag) == ("Release plan", "Release plan", "q3")
    tag_session(store, session_id, None)
    assert get_session_info(store, session_id).tag is None


def test_renaming_needs_a_title_and_a_session(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    with pytest.raises(ValueError):
        rename_session(store, session_id, "  ")
    with pytest.raises(FileNotFoundError):
        rename_session(store, "missing", "x")
    with pytest.raises(FileNotFoundError):
        tag_session(store, "missing", "x")
    assert get_session_info(store, "missing") is None


def test_fork_copies_the_conversation_under_a_new_id(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    first_message = get_session_messages(store, session_id)[0].uuid
    whole = fork_session(store, session_id, title="Try B")
    partial = fork_session(store, session_id, up_to_message_id=first_message)
    assert whole != session_id and len(list_sessions(store)) == 3
    assert get_session_info(store, whole).custom_title == "Try B"
    assert [m.type for m in get_session_messages(store, partial)] == ["user"]
    with pytest.raises(ValueError):
        fork_session(store, session_id, up_to_message_id="other:0")


def test_resume_continues_the_saved_conversation(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    llm = _Model()
    result = _run("And the date?", llm=llm, session_store=store, resume=session_id)
    assert result.session_id == session_id
    assert any("Plan the release." in text for text in llm.users[0])


def test_resume_with_fork_leaves_the_original_alone(saved: tuple[InMemorySessionStore, str]) -> None:
    store, session_id = saved
    before = len(get_session_messages(store, session_id))
    result = _run("Branch off.", llm=_Model(), session_store=store, resume=session_id, fork_session=True)
    assert result.session_id != session_id
    assert len(get_session_messages(store, session_id)) == before
    assert get_session_info(store, result.session_id) is not None


def test_resume_needs_a_known_session() -> None:
    with pytest.raises(ValueError, match="resume"):
        _run("x", llm=_Model(), session_store=InMemorySessionStore(), resume="missing")
