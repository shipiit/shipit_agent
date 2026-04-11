from shipit_agent.models import Message
from shipit_agent.session_manager import SessionManager
from shipit_agent.stores.session import InMemorySessionStore


class FakeAgent:
    """Minimal agent stub with chat_session support."""

    def __init__(self, store):
        self.session_store = store

    def chat_session(self, session_id):
        return _FakeChatSession(session_id, self.session_store)


class _FakeChatSession:
    def __init__(self, session_id, store):
        self.session_id = session_id
        self.store = store


def test_create_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat = mgr.create(agent, name="test session")
    assert chat.session_id is not None
    records = store.list_all()
    assert len(records) == 1
    assert records[0].metadata["name"] == "test session"


def test_resume_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat1 = mgr.create(agent, name="s1")
    chat2 = mgr.resume(agent, chat1.session_id)
    assert chat2.session_id == chat1.session_id


def test_resume_nonexistent_raises():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    try:
        mgr.resume(agent, "nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_list_sessions():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    mgr.create(agent, name="s1")
    mgr.create(agent, name="s2")
    assert len(mgr.list_sessions()) == 2


def test_archive_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)
    chat = mgr.create(agent, name="s1")
    mgr.archive(chat.session_id)
    record = store.load(chat.session_id)
    assert record is not None
    assert record.metadata.get("archived") is True


def test_fork_session():
    store = InMemorySessionStore()
    mgr = SessionManager(session_store=store)
    agent = FakeAgent(store)

    chat = mgr.create(agent, name="original")
    record = store.load(chat.session_id)
    assert record is not None
    record.messages = [
        Message(role="user", content="msg1"),
        Message(role="assistant", content="resp1"),
        Message(role="user", content="msg2"),
        Message(role="assistant", content="resp2"),
    ]
    store.save(record)

    forked = mgr.fork(agent, chat.session_id, from_message=2)
    forked_record = store.load(forked.session_id)
    assert forked_record is not None
    assert len(forked_record.messages) == 2
    assert forked_record.metadata["forked_from"] == chat.session_id
