from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class CredentialRecord:
    key: str
    provider: str
    secrets: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CredentialStore(Protocol):
    def get(self, key: str) -> CredentialRecord | None: ...

    def set(self, record: CredentialRecord) -> None: ...

    def list(self) -> list[CredentialRecord]: ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._records: dict[str, CredentialRecord] = {}

    def get(self, key: str) -> CredentialRecord | None:
        return self._records.get(key)

    def set(self, record: CredentialRecord) -> None:
        self._records[record.key] = record

    def list(self) -> list[CredentialRecord]:
        return list(self._records.values())


class FileCredentialStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _load_all(self) -> list[CredentialRecord]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            CredentialRecord(
                key=item["key"],
                provider=item["provider"],
                secrets=dict(item.get("secrets", {})),
                metadata=dict(item.get("metadata", {})),
            )
            for item in raw
        ]

    def _save_all(self, records: list[CredentialRecord]) -> None:
        payload = [
            {
                "key": record.key,
                "provider": record.provider,
                "secrets": record.secrets,
                "metadata": record.metadata,
            }
            for record in records
        ]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get(self, key: str) -> CredentialRecord | None:
        for record in self._load_all():
            if record.key == key:
                return record
        return None

    def set(self, record: CredentialRecord) -> None:
        records = self._load_all()
        replaced = False
        for index, existing in enumerate(records):
            if existing.key == record.key:
                records[index] = record
                replaced = True
                break
        if not replaced:
            records.append(record)
        self._save_all(records)

    def list(self) -> list[CredentialRecord]:
        return self._load_all()
