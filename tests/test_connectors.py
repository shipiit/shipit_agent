"""The connector catalog: manifest-per-directory loading, connect() transport
selection and OAuth gating, and the OAuth refresh/expiry layer.

The catalog is data — one ``manifest.yaml`` per ``connectors/catalog/<name>/`` —
so these tests double as a schema guard: a manifest that stops parsing, or a
hosted connector that forgets its OAuth gate, fails here.
"""

from __future__ import annotations

import os

import pytest

from shipit_agent.connectors import (
    connect,
    connector_categories,
    get_connector,
    list_connectors,
)
from shipit_agent.connectors.manifests import ManifestError, parse_manifest
from shipit_agent.connectors.registry import CATALOG_DIAGNOSTICS


# ── catalog loads cleanly ────────────────────────────────────────────────


def test_every_manifest_parses():
    connectors = list_connectors()
    assert len(connectors) >= 20
    # No manifest was skipped for being invalid.
    assert CATALOG_DIAGNOSTICS == []


def test_every_catalog_dir_loads():
    """Every ``catalog/<name>/manifest.yaml`` on disk becomes a connector.

    Guards the dev-works/install-breaks trap: a manifest that ships but fails
    to load would leave a smaller catalog with no error. The on-disk count must
    equal the loaded count, and nothing may be recorded as skipped.
    """
    from pathlib import Path

    from shipit_agent.connectors import registry

    on_disk = list((Path(registry.__file__).parent / "catalog").glob("*/manifest.yaml"))
    assert len(on_disk) == len(list_connectors())
    assert CATALOG_DIAGNOSTICS == []


def test_categories_are_grouped():
    cats = connector_categories()
    for expected in ("developer", "communication", "productivity", "data", "business"):
        assert expected in cats


def test_known_connectors_present():
    names = {c.name for c in list_connectors()}
    for expected in ("github", "slack", "linear", "jira", "notion", "stripe"):
        assert expected in names


# ── connect() picks the transport and enforces auth ──────────────────────


def test_hosted_oauth_requires_a_token():
    # linear is per-user OAuth — connecting without a token is a clear error,
    # never a silent unauthenticated call.
    with pytest.raises(ValueError, match="OAuth"):
        connect("linear")


def test_hosted_oauth_with_token_sets_bearer():
    server = connect("linear", token="lin_abc")
    assert server.transport.headers.get("authorization") == "Bearer lin_abc"


def test_hosted_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    server = connect("stripe")
    assert "authorization" in server.transport.headers


def test_stdio_missing_env_is_rejected(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
    with pytest.raises(ValueError, match="env var"):
        connect("slack")


def test_unknown_connector_lists_the_catalog():
    with pytest.raises(ValueError, match="Unknown connector"):
        connect("does-not-exist")


def test_connector_metadata_flows_through():
    linear = get_connector("linear")
    assert linear.hosted and linear.uses_oauth
    assert linear.oauth == "linear" and "read" in linear.scopes


def test_required_env_is_an_alias_for_env():
    from shipit_agent.connectors.base import Connector

    c = Connector(name="x", description="y", env=["X_TOKEN"])
    assert c.required_env == ["X_TOKEN"] == c.env


def test_invalid_manifest_is_skipped_with_a_diagnostic(tmp_path):
    """A broken manifest never breaks the catalog — it is recorded and skipped."""
    from shipit_agent.connectors import registry

    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "manifest.yaml").write_text(
        "name: good\ndescription: fine\n"
        "transport: {type: http, url: https://x}\n",
        encoding="utf-8",
    )
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "manifest.yaml").write_text(
        "name: broken\ndescription: y\ntransport: {type: http}\n",  # no url
        encoding="utf-8",
    )

    # Point the loader at our temp catalog and force a fresh scan.
    saved_dir, saved_reg = registry._CATALOG_DIR, dict(registry._REGISTRY)
    saved_diag, saved_loaded = list(registry.CATALOG_DIAGNOSTICS), registry._loaded
    try:
        registry._CATALOG_DIR = tmp_path
        registry._REGISTRY.clear()
        registry.CATALOG_DIAGNOSTICS.clear()
        registry._loaded = False
        registry.load_catalog()
        names = {c.name for c in registry.list_connectors()}
        assert "good" in names and "broken" not in names
        assert any("broken" in path for path, _err in registry.CATALOG_DIAGNOSTICS)
    finally:
        registry._CATALOG_DIR = saved_dir
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved_reg)
        registry.CATALOG_DIAGNOSTICS[:] = saved_diag
        registry._loaded = saved_loaded


# ── manifest parsing / validation ────────────────────────────────────────


def test_parse_rejects_bad_version():
    with pytest.raises(ManifestError, match="manifest_version"):
        parse_manifest({"manifest_version": 2, "name": "x", "description": "y"})


def test_parse_rejects_hosted_without_url():
    with pytest.raises(ManifestError, match="transport.url"):
        parse_manifest({
            "name": "x", "description": "y",
            "transport": {"type": "http"},
        })


def test_parse_maps_api_key_to_env_auth():
    c = parse_manifest({
        "name": "x", "description": "y",
        "transport": {"type": "stdio", "command": "run me"},
        "auth": {"type": "api_key", "env": [{"name": "X_TOKEN"}]},
    })
    assert c.auth == "env" and c.env == ["X_TOKEN"]
    assert c.command == ["run", "me"]


def test_parse_rejects_non_mapping():
    with pytest.raises(ManifestError, match="must be a mapping"):
        parse_manifest(["not", "a", "dict"])  # type: ignore[arg-type]


def test_parse_requires_name_and_description():
    with pytest.raises(ManifestError, match="missing required field 'name'"):
        parse_manifest({"description": "y"})
    with pytest.raises(ManifestError, match="missing required field 'description'"):
        parse_manifest({"name": "x"})


def test_parse_rejects_invalid_name():
    with pytest.raises(ManifestError, match="invalid name"):
        parse_manifest({"name": "bad name!", "description": "y",
                        "transport": {"type": "stdio", "command": "run"}})


def test_parse_rejects_unknown_transport_type():
    with pytest.raises(ManifestError, match="transport.type"):
        parse_manifest({"name": "x", "description": "y",
                        "transport": {"type": "carrier-pigeon"}})


def test_parse_rejects_stdio_without_command():
    with pytest.raises(ManifestError, match="transport.command"):
        parse_manifest({"name": "x", "description": "y",
                        "transport": {"type": "stdio"}})


def test_parse_rejects_unknown_auth_type():
    with pytest.raises(ManifestError, match="auth.type"):
        parse_manifest({"name": "x", "description": "y",
                        "transport": {"type": "stdio", "command": "run"},
                        "auth": {"type": "magic"}})


def test_parse_oauth_provider_defaults_to_name():
    c = parse_manifest({"name": "acme", "description": "y",
                        "transport": {"type": "http", "url": "https://x"},
                        "auth": {"type": "oauth"}})
    assert c.uses_oauth and c.oauth == "acme"  # provider defaults to the name


# ── connect(): overrides and error branches ──────────────────────────────


def test_connect_url_override_for_unknown_connector():
    # A bare URL with no catalog entry still yields a live hosted server.
    server = connect("my-proxy", url="https://mcp.example.com/sse", token="t")
    assert server.name == "my-proxy"


def test_connect_command_override_without_catalog(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _b: "/usr/bin/echo")
    server = connect("adhoc", command=["echo", "hi"])
    assert server.name == "adhoc"


def test_connect_no_command_is_rejected(monkeypatch):
    # A stdio connector with neither a manifest command nor an override.
    from shipit_agent.connectors import register
    from shipit_agent.connectors.base import Connector

    register(Connector(name="hollow", description="no launcher", kind="stdio"))
    with pytest.raises(ValueError, match="no launch command"):
        connect("hollow")


def test_connect_missing_launcher_binary(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _b: None)
    with pytest.raises(RuntimeError, match="not on PATH"):
        connect("adhoc", command=["totally-not-installed"])


# ── OAuth refresh + expiry ───────────────────────────────────────────────


def test_token_is_expired():
    from shipit_agent.integrations.oauth import token_is_expired

    assert token_is_expired({"expires_at": 1}) is True
    assert token_is_expired({}) is False  # non-expiring token stays valid


def test_oauth_presets_cover_the_big_apps():
    from shipit_agent.integrations.oauth import OAUTH_PRESETS

    for provider in ("github", "slack", "notion", "linear", "atlassian", "google"):
        assert provider in OAUTH_PRESETS
        helper = OAUTH_PRESETS[provider]("cid", "secret", "https://cb", scopes=["x"])
        assert hasattr(helper, "refresh_token")  # every preset can refresh
