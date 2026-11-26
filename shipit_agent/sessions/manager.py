"""Creating, loading and listing conversation sessions over a session store.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from typing import Any

from shipit_agent.stores.session import SessionRecord, SessionStore

from .forking import fork_contents


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
        cut = 0 < from_message < len(record.messages)
        messages, metadata = fork_contents(
            record.messages[:from_message] if from_message > 0 else record.messages,
            record.metadata,
            cut=cut,
        )
        fork_name = record.metadata.get("name", session_id)
        new_record = SessionRecord(
            session_id=new_id,
            messages=messages,
            metadata={
                **metadata,
                "name": f"Fork of {fork_name}",
                "forked_from": session_id,
                "forked_at_message": from_message,
            },
        )
        self.session_store.save(new_record)
        return self._chat_session(agent, new_id)

    def _chat_session(self, agent: Any, session_id: str) -> Any:
        """A chat on this manager's store, not the agent's own."""
        parameters = inspect.signature(agent.chat_session).parameters
        if "session_store" in parameters:
            return agent.chat_session(session_id=session_id, session_store=self.session_store)
        if "session_id" in parameters and parameters["session_id"].kind is not inspect.Parameter.POSITIONAL_ONLY:
            return agent.chat_session(session_id=session_id)
        return agent.chat_session(session_id)
