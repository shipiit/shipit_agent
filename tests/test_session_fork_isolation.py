"""A fork is its own copy, and a fork from an earlier message knows nothing said after it."""

from __future__ import annotations

import pytest

from shipit_agent.core.models import Message
from shipit_agent.sdk.sessions import fork_session
from shipit_agent.sessions.manager import SessionManager
from shipit_agent.stores.session import InMemorySessionStore, SessionRecord

LATER = {
    "verified_facts": [{"value": "later secret"}],
    "compaction_checkpoint": {"summary": "later secret"},
    "tool_discovery": {"schemas": {}},
}


class _Agent:
    def __init__(self, store: InMemorySessionStore) -> None:
        self.session_store = store

    def chat_session(self, session_id: str) -> str:
        return session_id


def _original(store: InMemorySessionStore) -> SessionRecord:
    record = SessionRecord(
        "orig",
        [Message(role="user", content="early"), Message(role="assistant", content="later secret")],
        {**LATER, "custom": {"labels": ["keep"]}},
    )
    store.save(record)
    return record


def _fork(store: InMemorySessionStore, how: str, cut: bool) -> SessionRecord:
    if how == "manager":
        new_id = SessionManager(store).fork(_Agent(store), "orig", from_message=1 if cut else -1)
    else:
        new_id = fork_session(store, "orig", up_to_message_id="orig:0" if cut else None)
    record = store.load(new_id)
    assert record is not None
    return record


@pytest.mark.parametrize("how", ["manager", "sdk"])
def test_a_fork_from_an_earlier_message_drops_what_was_learned_later(how: str) -> None:
    store = InMemorySessionStore()
    _original(store)
    fork = _fork(store, how, cut=True)
    assert [m.content for m in fork.messages] == ["early"]
    assert not set(LATER) & set(fork.metadata)
    assert fork.metadata["custom"] == {"labels": ["keep"]}


@pytest.mark.parametrize("how", ["manager", "sdk"])
def test_a_whole_fork_keeps_what_was_learned(how: str) -> None:
    store = InMemorySessionStore()
    _original(store)
    assert set(LATER) <= set(_fork(store, how, cut=False).metadata)


@pytest.mark.parametrize("how", ["manager", "sdk"])
@pytest.mark.parametrize("cut", [True, False])
def test_changing_a_fork_leaves_the_original_alone(how: str, cut: bool) -> None:
    store = InMemorySessionStore()
    original = _original(store)
    fork = _fork(store, how, cut=cut)
    fork.messages[0].content = "changed"
    fork.metadata["custom"]["labels"].append("fork only")
    assert original.messages[0].content == "early"
    assert original.metadata["custom"]["labels"] == ["keep"]


def test_the_manager_runs_chats_on_its_own_store() -> None:
    from shipit_agent import Agent
    from shipit_agent.llms import SimpleEchoLLM

    agent = Agent(llm=SimpleEchoLLM(), auto_use_skills=False)
    agents_store = agent.session_store
    store = InMemorySessionStore()
    manager = SessionManager(store)
    chat = manager.create(agent)
    chat.send("remember this")
    resumed = manager.resume(agent, chat.session_id)
    assert any(m.content == "remember this" for m in resumed.history())
    assert agent.session_store is agents_store
    assert agents_store is None or agents_store.load(chat.session_id) is None
