"""Saved sessions, the Claude Agent SDK way: list, read, rename, tag and fork.

The SDK keeps sessions as transcript files; shipit keeps them in a
:class:`~shipit_agent.stores.session.SessionStore` (in memory, or one JSON
file per session with ``FileSessionStore``), so each function takes the
store. A message's id is ``"<session_id>:<index>"``. Resume a session with
``AgentOptions(resume=session_id, session_store=store)``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from shipit_agent.stores.session import SessionRecord, SessionStore

__all__ = [
    "SDKSessionInfo",
    "SessionMessage",
    "fork_session",
    "get_session_info",
    "get_session_messages",
    "list_sessions",
    "rename_session",
    "tag_session",
]

_TITLE_KEY = "custom_title"
_TAG_KEY = "tag"


@dataclass(slots=True)
class SDKSessionInfo:
    session_id: str
    summary: str
    first_prompt: str
    custom_title: str | None
    tag: str | None
    message_count: int


@dataclass(slots=True)
class SessionMessage:
    type: str
    uuid: str
    session_id: str
    message: dict[str, Any]


def list_sessions(store: SessionStore, *, limit: int | None = None, offset: int = 0) -> list[SDKSessionInfo]:
    records = store.list_all()[offset:]
    return [_info(record) for record in (records[:limit] if limit is not None else records)]


def get_session_info(store: SessionStore, session_id: str) -> SDKSessionInfo | None:
    record = store.load(session_id)
    return None if record is None else _info(record)


def get_session_messages(
    store: SessionStore, session_id: str, *, limit: int | None = None, offset: int = 0
) -> list[SessionMessage]:
    """The session's user and assistant messages, oldest first."""
    record = store.load(session_id)
    if record is None:
        return []
    kept = [
        SessionMessage(m.role, f"{session_id}:{index}", session_id, m.to_dict())
        for index, m in enumerate(record.messages)
        if m.role in ("user", "assistant")
    ][offset:]
    return kept[:limit] if limit is not None else kept


def rename_session(store: SessionStore, session_id: str, title: str) -> None:
    if not title.strip():
        raise ValueError("a session title cannot be empty")
    record = _existing(store, session_id)
    record.metadata[_TITLE_KEY] = title.strip()
    store.save(record)


def tag_session(store: SessionStore, session_id: str, tag: str | None) -> None:
    """Set the session's tag; ``None`` clears it."""
    record = _existing(store, session_id)
    if tag is None:
        record.metadata.pop(_TAG_KEY, None)
    else:
        record.metadata[_TAG_KEY] = tag
    store.save(record)


def fork_session(
    store: SessionStore, session_id: str, *, up_to_message_id: str | None = None, title: str | None = None
) -> str:
    """Copy the session (up to and including a message) under a new id; that id."""
    record = _existing(store, session_id)
    messages = list(record.messages)
    if up_to_message_id is not None:
        prefix, _, index = up_to_message_id.rpartition(":")
        if prefix != session_id or not index.isdigit() or int(index) >= len(messages):
            raise ValueError(f"{up_to_message_id!r} is not a message of session {session_id!r}")
        messages = messages[: int(index) + 1]
    new_id = str(uuid.uuid4())
    metadata = {key: value for key, value in record.metadata.items() if key != _TAG_KEY}
    metadata["forked_from"] = session_id
    if title is not None:
        metadata[_TITLE_KEY] = title
    store.save(SessionRecord(session_id=new_id, messages=messages, metadata=metadata))
    return new_id


def _existing(store: SessionStore, session_id: str) -> SessionRecord:
    record = store.load(session_id)
    if record is None:
        raise FileNotFoundError(f"no session {session_id!r}")
    return record


def _info(record: SessionRecord) -> SDKSessionInfo:
    first = next((str(m.content) for m in record.messages if m.role == "user"), "")
    title = record.metadata.get(_TITLE_KEY)
    tag = record.metadata.get(_TAG_KEY)
    return SDKSessionInfo(
        session_id=record.session_id,
        summary=str(title) if title else first[:80],
        first_prompt=first,
        custom_title=str(title) if title else None,
        tag=str(tag) if tag else None,
        message_count=len(record.messages),
    )
