from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


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
    """File-backed credential store.

    .. warning::
        Secrets are stored as **plaintext JSON** — there is no encryption at
        rest. The file is created with ``0600`` (owner-only) permissions, but
        anyone who can read the file (or a backup of it) sees the secrets. For
        production use, back this with a secrets manager (Vault, AWS Secrets
        Manager, etc.) or an encrypted volume. Pass ``warn=False`` to silence
        the startup warning once you've acknowledged this.
    """

    def __init__(self, path: str | Path, *, warn: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if warn:
            logger.warning(
                "FileCredentialStore stores secrets as plaintext JSON at %s "
                "(no encryption at rest). Use a secrets manager for production.",
                self.path,
            )
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        self._restrict_permissions()

    def _restrict_permissions(self) -> None:
        """Best-effort: make the credentials file owner read/write only."""
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Non-POSIX filesystems (e.g. some Windows setups) may not support
            # chmod; the plaintext warning above still applies.
            pass

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
        # Atomic write so a concurrent reader / crash never sees truncated
        # JSON, then re-restrict permissions on the new file.
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

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
