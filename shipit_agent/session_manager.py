from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .stores.session import SessionRecord, SessionStore


@dataclass(slots=True)
class SessionManager:
    """Manage chat session lifecycle on top of a SessionStore."""

    session_store: SessionStore

    def create(
        self,
        agent: Any,
        *,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        session_id = str(uuid.uuid4())
        record = SessionRecord(
            session_id=session_id,
            messages=[],
            metadata={"name": name, **(metadata or {})},
        )
        self.session_store.save(record)
        return self._chat_session(agent, session_id)

    def resume(self, agent: Any, session_id: str) -> Any:
        if self.session_store.load(session_id) is None:
            raise ValueError(f"Session {session_id!r} not found")
        return self._chat_session(agent, session_id)

    def list_sessions(self) -> list[SessionRecord]:
        return self.session_store.list_all()

    def archive(self, session_id: str) -> None:
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id!r} not found")
        record.metadata["archived"] = True
        self.session_store.save(record)

    def fork(self, agent: Any, session_id: str, *, from_message: int = -1) -> Any:
        record = self.session_store.load(session_id)
        if record is None:
            raise ValueError(f"Session {session_id!r} not found")

        new_id = str(uuid.uuid4())
        messages = (
            record.messages[:from_message] if from_message > 0 else record.messages[:]
        )
        fork_name = record.metadata.get("name", session_id)
        new_record = SessionRecord(
            session_id=new_id,
            messages=deepcopy(messages),
            metadata={
                # Derived state may describe turns *after* the fork point.
                # Rebuild it from the fork's retained transcript instead.
                **deepcopy({key: value for key, value in record.metadata.items()
                            if key not in {"compaction_checkpoint", "verified_facts",
                                           "tool_discovery"}}),
                "name": f"Fork of {fork_name}",
                "forked_from": session_id,
                "forked_at_message": from_message,
            },
        )
        self.session_store.save(new_record)
        return self._chat_session(agent, new_id)

    def _chat_session(self, agent: Any, session_id: str) -> Any:
        if getattr(agent, "session_store", None) is not self.session_store:
            if not callable(getattr(agent, "clone", None)):
                raise ValueError("Agent must use the manager's session store or support clone()")
            agent = agent.clone(session_store=self.session_store)
        try:
            return agent.chat_session(session_id=session_id)
        except TypeError:
            return agent.chat_session(session_id)
