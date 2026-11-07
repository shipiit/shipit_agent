"""OAuth 2.0 helpers: build the authorization URL, exchange the code, refresh tokens."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib import parse, request

from .oauth_state import FileOAuthStateStore as FileOAuthStateStore
from .oauth_state import InMemoryOAuthStateStore as InMemoryOAuthStateStore
from .oauth_state import OAuthStateStore as OAuthStateStore


@dataclass(slots=True)
class OAuthClientConfig:
    """An OAuth client's endpoints, client id and secret, scopes and redirect URI."""
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]
    authorize_url: str
    token_url: str
    extras: dict[str, Any] | None = None




class OAuthHelper:
    """Run the OAuth authorization-code flow for one provider.

    :meth:`create_authorization_url` starts the flow, :meth:`exchange_code`
    finishes it and :meth:`refresh_token` renews an expired access token.
    """
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

    def exchange_code(
        self, *, code: str, state: str | None = None
    ) -> dict[str, Any]:
        """Exchange an authorization ``code`` for tokens.

        Pass the ``state`` returned to your redirect URI to validate it
        against the nonce stored by :meth:`create_authorization_url` — this
        is the CSRF defense for the OAuth flow. The nonce is consumed (single
        use) on a successful match.

        .. warning::
            If ``state`` is omitted the CSRF check is **skipped** for
            backward compatibility. Always pass the callback ``state`` in
            production; an unvalidated flow is vulnerable to login-CSRF and
            nonce replay.
        """
        if state is not None:
            stored = self.state_store.load(state)
            if stored is None:
                raise ValueError(
                    "Invalid or expired OAuth state — possible CSRF or replay."
                )
            # Consume the nonce so it can't be replayed.
            delete = getattr(self.state_store, "delete", None)
            if callable(delete):
                delete(state)

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
        return _stamp_expiry(dict(json.loads(raw)))

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a ``refresh_token`` for a fresh access token.

        This is the single most important piece of a durable connection: an
        access token lives an hour or two, a refresh token for weeks or months.
        Call this when :func:`token_is_expired` says the stored token is at or
        near expiry, then persist the returned token dict. Providers that do not
        return a new ``refresh_token`` keep the old one — carry it forward.

        Returns the token payload stamped with ``expires_at`` (epoch seconds).
        Raises on an HTTP error so a revoked/expired refresh token surfaces as a
        re-connect prompt rather than a silent unauthenticated call.
        """
        payload = parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
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
        token = _stamp_expiry(dict(json.loads(raw)))
        # Providers that rotate refresh tokens return a new one; those that
        # don't omit it — keep the caller's so the chain never breaks.
        token.setdefault("refresh_token", refresh_token)
        return token


def _stamp_expiry(token: dict[str, Any]) -> dict[str, Any]:
    """Add an absolute ``expires_at`` (epoch) from a relative ``expires_in``."""
    import time

    if "expires_at" not in token and token.get("expires_in"):
        try:
            token["expires_at"] = int(time.time()) + int(token["expires_in"])
        except (TypeError, ValueError):
            pass
    return token


def token_is_expired(token: dict[str, Any], *, skew_seconds: int = 120) -> bool:
    """True when a stored OAuth token should be refreshed before use.

    Reads ``expires_at`` (epoch seconds), refreshing ``skew_seconds`` early so
    a call never goes out on a token about to die. A token with no expiry is
    treated as still valid (some providers issue non-expiring tokens).
    """
    import time

    expires_at = token.get("expires_at")
    if not expires_at:
        return False
    try:
        return int(expires_at) - skew_seconds <= int(time.time())
    except (TypeError, ValueError):
        return False


#: Provider helpers live in oauth_providers, which imports OAuthHelper from
#: here; loading them on first use keeps both import paths without a cycle.
_PROVIDER_NAMES = frozenset(['GoogleOAuthHelper', 'OAUTH_PRESETS', 'SlackOAuthHelper', '_preset'])


def __getattr__(name: str) -> Any:
    if name in _PROVIDER_NAMES:
        from . import oauth_providers

        return getattr(oauth_providers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
