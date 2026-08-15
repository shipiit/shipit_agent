"""The one place that turns "a user connected Slack" into "the agent has a
valid Slack token right now".

:class:`OAuthCredentialManager` owns the whole per-user OAuth lifecycle:

* **authorize / complete** — start a connect flow and store the resulting token;
* **access_token** — hand back a *valid* token, refreshing transparently when it
  is at or past expiry and persisting the new one;
* **on_unauthorized** — force one refresh when a live call 401s (a token revoked
  or rotated out from under us);
* **status** — is this connection ``connected`` / ``expired`` / ``disconnected``,
  so a UI can show it and offer *reconnect*.

Concurrent refreshes for the same ``(user, connector)`` collapse to one via a
per-key lock, so a burst of calls after an expiry does not fire a burst of
refreshes. All storage goes through a :class:`~.tokens.TokenStore`; all provider
knowledge through an :class:`~..integrations.oauth.OAuthHelper` (its endpoints
and refresh grant). Nothing else holds a secret.
"""

from __future__ import annotations

import threading
from typing import Any

from ..integrations.oauth import (
    OAUTH_PRESETS,
    OAuthHelper,
    token_is_expired,
)
from ..mcp import RemoteMCPServer
from .registry import connect as _registry_connect
from .registry import get_connector
from .tokens import InMemoryTokenStore, Token, TokenStore


class NotConnected(Exception):
    """This user has never connected this integration — start the OAuth flow."""


class NeedsReconnect(Exception):
    """The stored token cannot be refreshed (revoked/expired) — re-authorize."""


class OAuthCredentialManager:
    def __init__(self, store: TokenStore | None = None) -> None:
        self.store: TokenStore = store or InMemoryTokenStore()
        self._helpers: dict[str, OAuthHelper] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ── provider registration ───────────────────────────────────────────
    def register(self, connector: str, helper: OAuthHelper) -> None:
        """Bind a configured :class:`OAuthHelper` (your app's client id/secret)
        to a connector, so this manager can run and refresh its OAuth flow."""
        self._helpers[connector] = helper

    def register_preset(
        self,
        connector: str,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        provider: str | None = None,
    ) -> None:
        """Register a connector using a built-in provider preset, taking default
        scopes from the connector's manifest when ``scopes`` is omitted."""
        c = get_connector(connector)
        prov = provider or (c.oauth if c else "") or connector
        factory = OAUTH_PRESETS.get(prov)
        if factory is None:
            raise ValueError(f"No OAuth preset for provider {prov!r}.")
        self.register(
            connector,
            factory(
                client_id, client_secret, redirect_uri,
                scopes=scopes or (c.scopes if c else []),
            ),
        )

    # ── connect flow ─────────────────────────────────────────────────────
    def authorize_url(
        self, *, user: str, connector: str, extra_params: dict[str, Any] | None = None
    ) -> str:
        """The URL to send the user to. The user + connector are carried in the
        OAuth ``state`` so :meth:`complete` knows where to store the token."""
        helper = self._require_helper(connector)
        return helper.create_authorization_url(
            state_payload={"user": user, "connector": connector},
            extra_params=extra_params,
        )["url"]

    def complete(
        self, *, connector: str, code: str, state: str, user: str | None = None
    ) -> Token:
        """Finish the flow: exchange ``code`` for a token and store it. The user
        is recovered from ``state`` (set by :meth:`authorize_url`) unless given."""
        helper = self._require_helper(connector)
        who = user
        if who is None:
            payload = helper.state_store.load(state) or {}
            who = payload.get("user")
        if not who:
            raise ValueError("Cannot complete OAuth: no user in state — pass user=.")
        token = helper.exchange_code(code=code, state=state)
        self.save(user=who, connector=connector, token=token)
        return token

    def save(self, *, user: str, connector: str, token: Token) -> None:
        """Store a token as-is (already carries ``expires_at`` from the helper)."""
        self.store.set(user, connector, token)

    # ── token access (the hot path) ──────────────────────────────────────
    def access_token(self, *, user: str, connector: str) -> str:
        """A valid access token, refreshed if needed. Raises :class:`NotConnected`
        if the user never connected, :class:`NeedsReconnect` if refresh fails."""
        token = self.store.get(user, connector)
        if not token:
            raise NotConnected(f"{user} has not connected '{connector}'.")
        if token_is_expired(token):
            token = self._refresh(user, connector, token)
        access = token.get("access_token")
        if not access:
            raise NeedsReconnect(f"'{connector}' token for {user} has no access_token.")
        return str(access)

    def on_unauthorized(self, *, user: str, connector: str) -> str:
        """Recover from a live 401: force one refresh and return the new token.
        Raises :class:`NeedsReconnect` if it cannot be refreshed."""
        token = self.store.get(user, connector)
        if not token:
            raise NotConnected(f"{user} has not connected '{connector}'.")
        return self._refresh(user, connector, token, force=True).get("access_token", "")

    def _refresh(
        self, user: str, connector: str, token: Token, *, force: bool = False
    ) -> Token:
        lock = self._lock_for(user, connector)
        with lock:
            # Re-read under the lock: a concurrent caller may have refreshed
            # already, so we don't fire a second identical refresh.
            fresh = self.store.get(user, connector) or token
            if not force and not token_is_expired(fresh):
                return fresh
            refresh_token = fresh.get("refresh_token")
            helper = self._helpers.get(connector)
            if not (helper and refresh_token):
                raise NeedsReconnect(
                    f"'{connector}' cannot be refreshed for {user} — reconnect. "
                    + ("no refresh_token stored." if not refresh_token
                       else "no OAuth helper registered.")
                )
            try:
                new = helper.refresh_token(str(refresh_token))
            except Exception as exc:  # noqa: BLE001 — a bad refresh = reconnect
                raise NeedsReconnect(
                    f"Refreshing '{connector}' for {user} failed: {exc}"
                ) from exc
            self.store.set(user, connector, new)
            return new

    # ── status + connect ─────────────────────────────────────────────────
    def status(self, *, user: str, connector: str) -> str:
        """``"connected"`` · ``"expired"`` (refreshable) · ``"disconnected"``."""
        token = self.store.get(user, connector)
        if not token:
            return "disconnected"
        if token_is_expired(token):
            return "expired" if token.get("refresh_token") else "disconnected"
        return "connected"

    def connections(self, *, user: str) -> dict[str, str]:
        """Every connector this user has, mapped to its status."""
        return {c: self.status(user=user, connector=c)
                for c in self.store.connectors_for(user)}

    def connect(self, connector: str, *, user: str, **kwargs: Any) -> RemoteMCPServer:
        """Build a live MCP server for this user — resolving (and refreshing) the
        token for OAuth connectors, and passing through for the rest."""
        c = get_connector(connector)
        token = None
        if c and c.uses_oauth:
            token = self.access_token(user=user, connector=connector)
        return _registry_connect(connector, token=token, **kwargs)

    # ── internals ────────────────────────────────────────────────────────
    def _require_helper(self, connector: str) -> OAuthHelper:
        helper = self._helpers.get(connector)
        if helper is None:
            raise ValueError(
                f"No OAuth helper registered for '{connector}'. Call "
                "register(...) or register_preset(...) with your app credentials."
            )
        return helper

    def _lock_for(self, user: str, connector: str) -> threading.Lock:
        key = (user, connector)
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock
