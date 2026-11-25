"""Each session id has a file of its own, whatever characters it contains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shipit_agent.core.models import Message
from shipit_agent.stores.session import FileSessionStore, SessionRecord


def _record(session_id: str, text: str) -> SessionRecord:
    return SessionRecord(session_id=session_id, messages=[Message(role="user", content=text)])


@pytest.mark.parametrize(("first", "second"), [("team/chat", "team_chat"), ("../chat", ".._chat"), ("Chat", "chat"),
                                               ("é/chat", "é_chat"), ("a b", "a_b"), ("x", "x.json")])
def test_distinct_ids_never_share_a_file(tmp_path: Path, first: str, second: str) -> None:
    store = FileSessionStore(tmp_path)
    store.save(_record(first, "first"))
    assert store.load(second) is None
    store.save(_record(second, "second"))
    assert store.load(first).messages[0].content == "first"
    assert store.load(second).messages[0].content == "second"


def test_no_id_can_write_outside_the_folder(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    for session_id in ("../../escape", "/etc/escape", "..", "a/../../b"):
        store.save(_record(session_id, "x"))
    assert sorted(p.parent for p in tmp_path.rglob("*.json")) == [tmp_path / "sessions"] * 4


def test_list_all_returns_every_session_with_its_exact_id(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    for session_id in ("team/chat", "team_chat", "plain"):
        store.save(_record(session_id, session_id))
    assert sorted(r.session_id for r in store.list_all()) == ["plain", "team/chat", "team_chat"]


def test_a_session_saved_by_an_older_version_is_still_found_and_moved_on_save(tmp_path: Path) -> None:
    legacy = tmp_path / "team_chat.json"
    legacy.write_text(json.dumps({"session_id": "team/chat", "messages": [{"role": "user", "content": "old"}], "metadata": {}}))
    store = FileSessionStore(tmp_path)
    assert store.load("team/chat").messages[0].content == "old"
    # The old file belongs to "team/chat" only, not to the id its name also fits.
    assert store.load("team_chat") is None
    assert [r.session_id for r in store.list_all()] == ["team/chat"]
    store.save(_record("team/chat", "new"))
    assert not legacy.exists() and store.load("team/chat").messages[0].content == "new"
    assert [r.session_id for r in store.list_all()] == ["team/chat"]


def test_an_unreadable_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json")
    store = FileSessionStore(tmp_path)
    store.save(_record("ok", "x"))
    assert [r.session_id for r in store.list_all()] == ["ok"]
