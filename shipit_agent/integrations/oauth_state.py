"""Where an OAuth flow keeps its state between the redirect and the callback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class OAuthStateStore(Protocol):
    """Where pending OAuth ``state`` values are kept between redirect and callback."""
    def save(self, state: str, payload: dict[str, Any]) -> None: ...

    def load(self, state: str) -> dict[str, Any] | None: ...

    def delete(self, state: str) -> None: ...


class InMemoryOAuthStateStore:
    """An OAuth state store that lives for the life of the process."""
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def save(self, state: str, payload: dict[str, Any]) -> None:
        self._items[state] = dict(payload)

    def load(self, state: str) -> dict[str, Any] | None:
        return self._items.get(state)

    def delete(self, state: str) -> None:
        self._items.pop(state, None)


class FileOAuthStateStore:
    """An OAuth state store kept in a JSON file, for flows that span processes."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load_all(self) -> dict[str, dict[str, Any]]:
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: str, payload: dict[str, Any]) -> None:
        data = self._load_all()
        data[state] = dict(payload)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, state: str) -> dict[str, Any] | None:
        return self._load_all().get(state)

    def delete(self, state: str) -> None:
        data = self._load_all()
        if state in data:
            del data[state]
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
