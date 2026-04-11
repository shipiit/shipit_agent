from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import parse, request


@dataclass(slots=True)
class OAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]
    authorize_url: str
    token_url: str
    extras: dict[str, Any] | None = None


class OAuthStateStore(Protocol):
    def save(self, state: str, payload: dict[str, Any]) -> None: ...

    def load(self, state: str) -> dict[str, Any] | None: ...


class InMemoryOAuthStateStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def save(self, state: str, payload: dict[str, Any]) -> None:
        self._items[state] = dict(payload)

    def load(self, state: str) -> dict[str, Any] | None:
        return self._items.get(state)


class FileOAuthStateStore:
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


class OAuthHelper:
    def __init__(
        self, config: OAuthClientConfig, *, state_store: OAuthStateStore | None = None
    ) -> None:
        self.config = config
        self.state_store = state_store or InMemoryOAuthStateStore()

    def create_authorization_url(
        self,
        *,
        state_payload: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        state = secrets.token_urlsafe(24)
        self.state_store.save(state, state_payload or {})
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "response_type": "code",
            "state": state,
            **(self.config.extras or {}),
            **(extra_params or {}),
        }
        return {
            "state": state,
            "url": f"{self.config.authorize_url}?{parse.urlencode(params)}",
        }

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        payload = parse.urlencode(
            {
                "code": code,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": self.config.redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")
        req = request.Request(
            self.config.token_url,
            data=payload,
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with request.urlopen(req, timeout=30.0) as response:  # nosec B310
            raw = response.read().decode("utf-8")
        return dict(json.loads(raw))


class GoogleOAuthHelper(OAuthHelper):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: list[str],
        state_store: OAuthStateStore | None = None,
    ) -> None:
        super().__init__(
            OAuthClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scopes=scopes,
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                extras={"access_type": "offline", "prompt": "consent"},
            ),
            state_store=state_store,
        )


class SlackOAuthHelper(OAuthHelper):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: list[str],
        state_store: OAuthStateStore | None = None,
    ) -> None:
        super().__init__(
            OAuthClientConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scopes=scopes,
                authorize_url="https://slack.com/oauth/v2/authorize",
                token_url="https://slack.com/api/oauth.v2.access",
            ),
            state_store=state_store,
        )
