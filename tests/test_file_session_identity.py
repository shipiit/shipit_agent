import json

import pytest

from shipit_agent.models import Message
from shipit_agent.stores.session import FileSessionStore, SessionRecord


@pytest.mark.parametrize("first,second", [
    ("team/chat", "team_chat"), ("team\\chat", "team_chat"),
    ("../chat", ".._chat"), ("é/chat", "é_chat"),
    ("Chat", "chat"),
])
def test_distinct_chat_ids_never_share_a_file(tmp_path, first, second):
    store = FileSessionStore(tmp_path)
    for ident in (first, second):
        store.save(SessionRecord(ident, [Message(role="user", content=ident)]))
    for ident in (first, second):
        record = store.load(ident)
        assert record.session_id == ident
        assert record.messages[0].content == ident
        assert store._path_for(ident).parent == tmp_path
    assert {r.session_id for r in store.list_all()} == {first, second}
    assert store._path_for(first).name.casefold() != store._path_for(second).name.casefold()


def test_legacy_collision_cannot_expose_another_chat(tmp_path):
    (tmp_path / "team_chat.json").write_text(json.dumps({
        "session_id": "team/chat", "messages": [], "metadata": {},
    }))
    store = FileSessionStore(tmp_path)
    assert store.load("team_chat") is None
    assert store.load("team/chat").session_id == "team/chat"
    store.save(SessionRecord("team/chat"))
    assert len(store.list_all()) == 1


def test_long_session_ids_are_bounded(tmp_path):
    store = FileSessionStore(tmp_path)
    ident = "long" * 1000
    store.save(SessionRecord(ident))
    assert store.load(ident).session_id == ident
