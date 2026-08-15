"""Where a user's connector tokens live.

A :class:`TokenStore` holds one OAuth token per ``(user, connector)`` — the
access token, its refresh token, and ``expires_at``. It is deliberately small
and pluggable: an in-memory store for tests and single-process apps, a
file-backed store for a daemon, or your own backed by a database. The
credential manager (see :mod:`.oauth_manager`) reads and writes through this
protocol and never elsewhere, so swapping storage never touches refresh logic.

A token is a plain dict — the exact shape a provider's token endpoint returns
(``access_token``, ``refresh_token``, ``expires_at``, ``scope`` …).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

Token = dict[str, Any]


@runtime_checkable
class TokenStore(Protocol):
    def get(self, user: str, connector: str) -> Token | None: ...

    def set(self, user: str, connector: str, token: Token) -> None: ...

    def delete(self, user: str, connector: str) -> None: ...

    def connectors_for(self, user: str) -> list[str]: ...


class InMemoryTokenStore:
    """Process-local token store — perfect for tests and single-process apps."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Token] = {}
        self._lock = threading.Lock()

    def get(self, user: str, connector: str) -> Token | None:
        with self._lock:
            token = self._items.get((user, connector))
            return dict(token) if token else None

    def set(self, user: str, connector: str, token: Token) -> None:
        with self._lock:
            self._items[(user, connector)] = dict(token)

    def delete(self, user: str, connector: str) -> None:
        with self._lock:
            self._items.pop((user, connector), None)

    def connectors_for(self, user: str) -> list[str]:
        with self._lock:
            return sorted(c for (u, c) in self._items if u == user)


class FileTokenStore:
    """Token store backed by ``<root>/<user>/<connector>.json``.

    One file per connection so an external refresh (a cron job) can update a
    single token without racing the rest. Files are written ``0600``. Tokens
    are stored as plaintext JSON — put ``root`` on an encrypted volume, or
    supply your own encrypting store, for anything sensitive.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user: str, connector: str) -> Path:
        safe_user = "".join(c if c.isalnum() or c in "-_@." else "_" for c in user)
        safe_conn = "".join(c if c.isalnum() or c in "-_" else "_" for c in connector)
        return self.root / safe_user / f"{safe_conn}.json"

    def get(self, user: str, connector: str) -> Token | None:
        path = self._path(user, connector)
        if not path.exists():
            return None
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def set(self, user: str, connector: str, token: Token) -> None:
        path = self._path(user, connector)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(token, indent=2), encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass

    def delete(self, user: str, connector: str) -> None:
        with self._lock:
            self._path(user, connector).unlink(missing_ok=True)

    def connectors_for(self, user: str) -> list[str]:
        user_dir = self._path(user, "_").parent
        if not user_dir.is_dir():
            return []
        return sorted(p.stem for p in user_dir.glob("*.json"))
