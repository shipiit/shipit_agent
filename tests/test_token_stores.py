"""The connector token-store layer — where a user's OAuth tokens live.

Both stores implement the same tiny :class:`TokenStore` protocol
(``get`` / ``set`` / ``delete`` / ``connectors_for``), so the credential
manager never cares which one it holds. These tests pin that contract for the
process-local :class:`InMemoryTokenStore` and the daemon-friendly
:class:`FileTokenStore` — including the file store's on-disk layout, path
sanitisation, ``0600`` permissions, and its graceful handling of a missing or
corrupt token file (a half-written file must read as "not connected", never a
crash).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from shipit_agent.connectors.tokens import (
    FileTokenStore,
    InMemoryTokenStore,
    TokenStore,
)

TOKEN = {"access_token": "abc", "refresh_token": "r1", "expires_at": 9999999999}


# ── both stores satisfy the protocol and the round-trip ──────────────────


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path) -> TokenStore:
    if request.param == "memory":
        return InMemoryTokenStore()
    return FileTokenStore(tmp_path / "tokens")


def test_store_is_a_tokenstore(store):
    assert isinstance(store, TokenStore)


def test_set_then_get_round_trips(store):
    store.set("user-1", "linear", TOKEN)
    assert store.get("user-1", "linear") == TOKEN


def test_get_returns_a_copy_not_the_stored_object(store):
    store.set("user-1", "linear", TOKEN)
    got = store.get("user-1", "linear")
    got["access_token"] = "mutated"
    # Mutating the returned dict must not corrupt what the store holds.
    assert store.get("user-1", "linear")["access_token"] == "abc"


def test_missing_token_is_none(store):
    assert store.get("nobody", "linear") is None


def test_delete_removes_the_token(store):
    store.set("user-1", "linear", TOKEN)
    store.delete("user-1", "linear")
    assert store.get("user-1", "linear") is None


def test_delete_missing_is_a_noop(store):
    # Deleting a connection that was never stored must not raise.
    store.delete("ghost", "linear")


def test_connectors_for_lists_only_that_user_sorted(store):
    store.set("user-1", "slack", TOKEN)
    store.set("user-1", "linear", TOKEN)
    store.set("user-2", "github", TOKEN)
    assert store.connectors_for("user-1") == ["linear", "slack"]
    assert store.connectors_for("user-2") == ["github"]
    assert store.connectors_for("stranger") == []


def test_set_overwrites(store):
    store.set("user-1", "linear", TOKEN)
    store.set("user-1", "linear", {"access_token": "new"})
    assert store.get("user-1", "linear") == {"access_token": "new"}


# ── FileTokenStore: on-disk layout, sanitisation, permissions, resilience ─


def test_file_layout_is_user_dir_connector_json(tmp_path):
    store = FileTokenStore(tmp_path)
    store.set("user-1", "linear", TOKEN)
    path = tmp_path / "user-1" / "linear.json"
    assert path.exists()
    assert json.loads(path.read_text()) == TOKEN


def test_file_root_is_created_eagerly(tmp_path):
    root = tmp_path / "deep" / "nested" / "tokens"
    FileTokenStore(root)
    assert root.is_dir()


def test_file_sanitises_unsafe_path_segments(tmp_path):
    store = FileTokenStore(tmp_path)
    # A hostile user id / connector name must not escape the root.
    store.set("../../etc", "a/b", TOKEN)
    assert store.get("../../etc", "a/b") == TOKEN
    # Nothing was written outside the root.
    written = list(tmp_path.rglob("*.json"))
    assert len(written) == 1
    assert tmp_path in written[0].parents


def test_file_email_user_id_is_kept_readable(tmp_path):
    store = FileTokenStore(tmp_path)
    store.set("rahul@iamrraj.com", "linear", TOKEN)
    # '@' '.' '-' '_' are preserved so a token dir is recognisable on disk.
    assert (tmp_path / "rahul@iamrraj.com" / "linear.json").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file mode")
def test_file_is_written_0600(tmp_path):
    store = FileTokenStore(tmp_path)
    store.set("user-1", "linear", TOKEN)
    mode = (tmp_path / "user-1" / "linear.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_file_corrupt_json_reads_as_none(tmp_path):
    store = FileTokenStore(tmp_path)
    store.set("user-1", "linear", TOKEN)
    (tmp_path / "user-1" / "linear.json").write_text("{ not json", encoding="utf-8")
    # A half-written file is "not connected", not an exception.
    assert store.get("user-1", "linear") is None


def test_file_connectors_for_unknown_user_is_empty(tmp_path):
    store = FileTokenStore(tmp_path)
    assert store.connectors_for("never-seen") == []


def test_file_survives_a_fresh_store_on_the_same_root(tmp_path):
    FileTokenStore(tmp_path).set("user-1", "linear", TOKEN)
    # A new process (new store object, same root) sees the persisted token.
    assert FileTokenStore(tmp_path).get("user-1", "linear") == TOKEN
