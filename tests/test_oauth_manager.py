"""The credential manager: a stored token is refreshed transparently on
expiry, a 401 forces one recovery refresh, status reflects reality, and OAuth
connectors resolve a per-user token through ``connect()``.

A fake OAuth helper stands in for the network so the refresh contract is tested
without a real provider.
"""

from __future__ import annotations

import pytest

from shipit_agent.connectors import (
    NeedsReconnect,
    NotConnected,
    OAuthCredentialManager,
)
from shipit_agent.connectors.oauth_manager import token_is_expired
from shipit_agent.integrations.oauth import InMemoryOAuthStateStore


class FakeHelper:
    """An OAuthHelper stand-in: each refresh hands back a new access token."""

    def __init__(self) -> None:
        self.refreshes = 0
        self.state_store = InMemoryOAuthStateStore()

    def create_authorization_url(self, *, state_payload=None, extra_params=None):
        self.state_store.save("st", state_payload or {})
        return {"state": "st", "url": "https://auth/x?state=st"}

    def exchange_code(self, *, code, state=None):
        return {"access_token": "A1", "refresh_token": "R1", "expires_at": 1}

    def refresh_token(self, refresh_token: str):
        self.refreshes += 1
        # Fresh token, valid far into the future.
        return {
            "access_token": f"A{self.refreshes + 1}",
            "refresh_token": refresh_token,
            "expires_at": 9_999_999_999,
        }


def _mgr():
    m = OAuthCredentialManager()
    m.register("linear", FakeHelper())
    return m


def test_valid_token_is_returned_as_is():
    m = _mgr()
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 9_999_999_999})
    assert m.access_token(user="u", connector="linear") == "A1"


def test_expired_token_is_refreshed_and_persisted():
    m = _mgr()
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 1})
    # First access refreshes (token is past expiry)…
    assert m.access_token(user="u", connector="linear") == "A2"
    # …and the fresh token is stored, so the next access does NOT refresh again.
    helper = m._helpers["linear"]
    assert m.access_token(user="u", connector="linear") == "A2"
    assert helper.refreshes == 1


def test_401_forces_one_refresh():
    m = _mgr()
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 9_999_999_999})
    assert m.on_unauthorized(user="u", connector="linear") == "A2"


def test_not_connected_and_needs_reconnect():
    m = _mgr()
    with pytest.raises(NotConnected):
        m.access_token(user="nobody", connector="linear")
    # Expired with no refresh token → reconnect required.
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "expires_at": 1})
    with pytest.raises(NeedsReconnect):
        m.access_token(user="u", connector="linear")


def test_status_reflects_the_token():
    m = _mgr()
    assert m.status(user="u", connector="linear") == "disconnected"
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 9_999_999_999})
    assert m.status(user="u", connector="linear") == "connected"
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 1})
    assert m.status(user="u", connector="linear") == "expired"
    assert m.connections(user="u") == {"linear": "expired"}


def test_connect_resolves_token_for_oauth_connector():
    m = _mgr()
    m.save(user="u", connector="linear",
           token={"access_token": "A9", "refresh_token": "R1", "expires_at": 9_999_999_999})
    server = m.connect("linear", user="u")
    assert server.transport.headers.get("authorization") == "Bearer A9"


def test_authorize_and_complete_roundtrip():
    m = _mgr()
    url = m.authorize_url(user="u", connector="linear")
    assert "auth" in url
    token = m.complete(connector="linear", code="c", state="st")
    assert token["access_token"] == "A1"
    assert m.status(user="u", connector="linear") in ("connected", "expired")


def test_register_preset_uses_manifest_scopes():
    m = OAuthCredentialManager()
    m.register_preset("linear", client_id="c", client_secret="s",
                      redirect_uri="https://cb")
    # The helper is configured with the connector's manifest scopes.
    helper = m._helpers["linear"]
    assert "read" in helper.config.scopes
    assert token_is_expired  # imported symbol is available for callers


# ── error branches: misconfiguration and refresh failure ─────────────────


def test_register_preset_unknown_provider_raises():
    m = OAuthCredentialManager()
    with pytest.raises(ValueError, match="No OAuth preset"):
        m.register_preset("mystery", client_id="c", client_secret="s",
                          redirect_uri="https://cb", provider="nope-provider")


def test_authorize_without_helper_raises():
    m = OAuthCredentialManager()
    with pytest.raises(ValueError, match="No OAuth helper"):
        m.authorize_url(user="u", connector="unregistered")


def test_complete_without_user_in_state_raises():
    m = _mgr()
    # A callback whose state carries no user, and no user= passed in.
    with pytest.raises(ValueError, match="no user in state"):
        m.complete(connector="linear", code="c", state="unknown-state")


def test_token_without_access_token_needs_reconnect():
    m = _mgr()
    # Valid (unexpired) but structurally broken — no access_token to hand back.
    m.save(user="u", connector="linear",
           token={"refresh_token": "R1", "expires_at": 9_999_999_999})
    with pytest.raises(NeedsReconnect, match="no access_token"):
        m.access_token(user="u", connector="linear")


def test_on_unauthorized_unknown_user_raises():
    m = _mgr()
    with pytest.raises(NotConnected):
        m.on_unauthorized(user="ghost", connector="linear")


def test_concurrent_refresh_dedupes_to_one():
    # Simulate the race the lock guards: this caller entered _refresh with a
    # stale snapshot, but another caller already stored a fresh token. The
    # re-read under the lock must return that token WITHOUT a second refresh.
    m = _mgr()
    helper = m._helpers["linear"]
    fresh = {"access_token": "A9", "refresh_token": "R1", "expires_at": 9_999_999_999}
    m.save(user="u", connector="linear", token=fresh)
    stale = {"access_token": "A1", "refresh_token": "R1", "expires_at": 1}
    assert m._refresh("u", "linear", stale)["access_token"] == "A9"
    assert helper.refreshes == 0  # no network refresh fired


def test_refresh_failure_becomes_needs_reconnect():
    class BrokenHelper(FakeHelper):
        def refresh_token(self, refresh_token: str):
            raise RuntimeError("provider said 400")

    m = OAuthCredentialManager()
    m.register("linear", BrokenHelper())
    m.save(user="u", connector="linear",
           token={"access_token": "A1", "refresh_token": "R1", "expires_at": 1})
    with pytest.raises(NeedsReconnect, match="failed"):
        m.access_token(user="u", connector="linear")
