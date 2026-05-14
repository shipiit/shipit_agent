"""``MediaStore`` — resolve ``[media:<uuid>]`` refs to fetchable URLs.

Used when users paste ``[media:abc123]`` into a prompt. The store maps
that UUID back to the underlying URL (or local file path) plus a MIME
type and optional alt text.

Three reference implementations:

* ``InMemoryMediaStore`` — dict-backed, ideal for tests and notebooks.
* ``FileMediaStore`` — JSON-backed, persists across process restarts.
* Bring your own — implement the ``MediaStore`` protocol against S3, a
  database, or whatever else you store user uploads in.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class StoredMedia:
    """One uploaded asset, looked up by ID."""

    id: str
    url: str
    mime: str | None = None
    alt: str = ""
    bytes: int | None = None
    """Optional size hint to short-circuit ``max_size_mb`` validation."""

    metadata: dict[str, str] = field(default_factory=dict)
    """User-defined metadata. Not interpreted by the parser."""


class MediaStore(Protocol):
    """Lookup interface for resolving media IDs to ``StoredMedia``."""

    def resolve(self, media_id: str) -> StoredMedia | None: ...

    def put(self, media: StoredMedia) -> str: ...

    def list_all(self) -> list[StoredMedia]: ...

    def delete(self, media_id: str) -> bool: ...


def _ensure_id(media: StoredMedia) -> StoredMedia:
    """Return ``media`` with a non-empty id (auto-generated if missing)."""
    if media.id:
        return media
    return replace(media, id=uuid.uuid4().hex)


class InMemoryMediaStore:
    """Pure in-memory store. Fast, ephemeral, perfect for tests."""

    def __init__(self, items: list[StoredMedia] | None = None) -> None:
        self._items: dict[str, StoredMedia] = {}
        for item in items or []:
            self._items[item.id] = item

    def resolve(self, media_id: str) -> StoredMedia | None:
        return self._items.get(media_id)

    def put(self, media: StoredMedia) -> str:
        media = _ensure_id(media)
        self._items[media.id] = media
        return media.id

    def list_all(self) -> list[StoredMedia]:
        return list(self._items.values())

    def delete(self, media_id: str) -> bool:
        return self._items.pop(media_id, None) is not None

    def __len__(self) -> int:
        return len(self._items)


class FileMediaStore:
    """JSON-backed store. Persists across process restarts.

    Format::

        {
          "abc123": {"id": "abc123", "url": "https://...", "mime": "image/png", "alt": "..."},
          ...
        }
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._cache: dict[str, StoredMedia] | None = None

    def _load(self) -> dict[str, StoredMedia]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._cache = {}
            return self._cache
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._cache = {k: StoredMedia(**v) for k, v in raw.items()}
        return self._cache

    def _flush(self) -> None:
        if self._cache is None:
            return
        payload = {k: asdict(v) for k, v in self._cache.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def resolve(self, media_id: str) -> StoredMedia | None:
        return self._load().get(media_id)

    def put(self, media: StoredMedia) -> str:
        media = _ensure_id(media)
        self._load()[media.id] = media
        self._flush()
        return media.id

    def list_all(self) -> list[StoredMedia]:
        return list(self._load().values())

    def delete(self, media_id: str) -> bool:
        cache = self._load()
        if media_id in cache:
            del cache[media_id]
            self._flush()
            return True
        return False
