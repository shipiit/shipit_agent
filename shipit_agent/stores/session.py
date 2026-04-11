from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from shipit_agent.models import Message


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class SessionStore(Protocol):
    def load(self, session_id: str) -> SessionRecord | None: ...

    def save(self, record: SessionRecord) -> None: ...

    def list_all(self) -> list[SessionRecord]: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def load(self, session_id: str) -> SessionRecord | None:
        return self._records.get(session_id)

    def save(self, record: SessionRecord) -> None:
        self._records[record.session_id] = record

    def list_all(self) -> list[SessionRecord]:
        return list(self._records.values())


class FileSessionStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_")
        return self.root_dir / f"{safe}.json"

    def load(self, session_id: str) -> SessionRecord | None:
        path = self._path_for(session_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SessionRecord(
            session_id=raw["session_id"],
            messages=[
                Message(
                    role=item["role"],
                    content=item["content"],
                    name=item.get("name"),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in raw.get("messages", [])
            ],
            metadata=dict(raw.get("metadata", {})),
        )

    def save(self, record: SessionRecord) -> None:
        path = self._path_for(record.session_id)
        payload = {
            "session_id": record.session_id,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "name": message.name,
                    "metadata": message.metadata,
                }
                for message in record.messages
            ],
            "metadata": record.metadata,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_all(self) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for path in sorted(self.root_dir.glob("*.json")):
            record = self.load(path.stem)
            if record is not None:
                records.append(record)
        return records
