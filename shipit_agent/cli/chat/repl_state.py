"""The session's state: RAG indexing, and clearing, saving and loading history."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from shipit_agent.core.models import Message

from .style import dim, red


class StateMixin:
    """The session's state: RAG indexing, and clearing, saving and loading history."""

    def _index_file(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /index <path>"))
            return
        if self.rag is None:
            self._init_default_rag(output)
        try:
            chunks = self.rag.index_file(path)
            output(dim(f"[chat] indexed {len(chunks)} chunks from {path}"))
            self._rebuild_agent(output)
        except Exception as exc:
            output(red(f"[chat] index failed: {exc}"))

    def _init_default_rag(self, output) -> None:
        from shipit_agent.rag import RAG, HashingEmbedder

        self.rag = RAG.default(embedder=HashingEmbedder(dimension=512))
        output(dim("[chat] initialised default in-memory RAG (HashingEmbedder)"))

    def _clear_history(self, output) -> None:
        if self.chat is None:
            output(dim("[chat] no history to clear"))
            return
        record = self.session_store.load(self.session_id)
        if record:
            record.messages.clear()
            self.session_store.save(record)
        output(dim("[chat] history cleared"))

    def _reset_session(self, output) -> None:
        new_id = f"chat-{uuid.uuid4().hex[:8]}"
        self.session_id = new_id
        self.last_sources = []
        self._rebuild_agent(output)
        output(dim(f"[chat] new session: {new_id}"))

    def _save_history(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /save <path>"))
            return
        if self.chat is None:
            output(dim("[chat] this agent type has no chat history"))
            return
        history = self.chat.history()
        data = {
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "messages": [
                {"role": m.role, "content": m.content, "name": m.name} for m in history
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        output(dim(f"[chat] saved {len(history)} messages → {path}"))

    def _load_history(self, path: str, output) -> None:
        if not path:
            output(red("[chat] usage: /load <path>"))
            return
        if not os.path.exists(path):
            output(red(f"[chat] file not found: {path}"))
            return
        if self.chat is None:
            output(
                dim(
                    "[chat] current agent type has no chat history; switch to /agent agent or /agent deep first."
                )
            )
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        new_id = data.get("session_id", f"chat-{uuid.uuid4().hex[:8]}")
        self.session_id = new_id
        if data.get("agent_type") and data["agent_type"] != self.agent_type:
            self.agent_type = data["agent_type"]
            self._rebuild_agent(output)
        else:
            self._rebuild_agent(output)
        record = self.session_store.load(new_id)
        if record is None:
            from shipit_agent.stores.session import SessionRecord

            record = SessionRecord(session_id=new_id, messages=[])
        record.messages = [
            Message(role=m["role"], content=m["content"], name=m.get("name"))
            for m in data.get("messages", [])
        ]
        self.session_store.save(record)
        output(dim(f"[chat] loaded {len(record.messages)} messages from {path}"))
