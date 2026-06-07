"""Regression tests for OAuth state/CSRF validation (SEC-4)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from shipit_agent.integrations.oauth import (
    FileOAuthStateStore,
    InMemoryOAuthStateStore,
    OAuthClientConfig,
    OAuthHelper,
)


def _config() -> OAuthClientConfig:
    return OAuthClientConfig(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://app/cb",
        scopes=["read"],
        authorize_url="https://auth/authorize",
        token_url="https://auth/token",
    )


def _fake_token_response(payload: dict):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    cm.__exit__.return_value = False
    return cm


def test_valid_state_is_accepted_and_consumed():
    helper = OAuthHelper(_config(), state_store=InMemoryOAuthStateStore())
    auth = helper.create_authorization_url(state_payload={"u": 1})
    state = auth["state"]

    with mock.patch(
        "shipit_agent.integrations.oauth.request.urlopen",
        return_value=_fake_token_response({"access_token": "abc"}),
    ):
        token = helper.exchange_code(code="thecode", state=state)
    assert token["access_token"] == "abc"
    # Nonce was consumed.
    assert helper.state_store.load(state) is None


def test_unknown_state_is_rejected():
    helper = OAuthHelper(_config(), state_store=InMemoryOAuthStateStore())
    with pytest.raises(ValueError, match="state"):
        helper.exchange_code(code="thecode", state="never-issued")


def test_state_cannot_be_replayed():
    helper = OAuthHelper(_config(), state_store=InMemoryOAuthStateStore())
    state = helper.create_authorization_url()["state"]
    with mock.patch(
        "shipit_agent.integrations.oauth.request.urlopen",
        return_value=_fake_token_response({"access_token": "abc"}),
    ):
        helper.exchange_code(code="c1", state=state)
        with pytest.raises(ValueError, match="state"):
            helper.exchange_code(code="c2", state=state)


def test_backward_compat_no_state_skips_validation():
    helper = OAuthHelper(_config(), state_store=InMemoryOAuthStateStore())
    with mock.patch(
        "shipit_agent.integrations.oauth.request.urlopen",
        return_value=_fake_token_response({"access_token": "abc"}),
    ):
        # No state passed -> legacy behavior, no CSRF check.
        token = helper.exchange_code(code="thecode")
    assert token["access_token"] == "abc"


def test_file_store_delete(tmp_path):
    store = FileOAuthStateStore(tmp_path / "s.json")
    store.save("k", {"a": 1})
    assert store.load("k") == {"a": 1}
    store.delete("k")
    assert store.load("k") is None
    # Deleting a missing key is a no-op.
    store.delete("missing")
