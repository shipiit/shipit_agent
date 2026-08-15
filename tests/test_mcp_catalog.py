"""Tests for the prebuilt MCP catalog (connect_mcp / list_mcp_catalog)."""

from __future__ import annotations

import pytest

from shipit_agent import (
    MCP_CATALOG,
    RemoteMCPServer,
    connect_mcp,
    list_mcp_catalog,
)


class TestCatalog:
    def test_catalog_has_core_servers(self) -> None:
        for name in ("filesystem", "github", "slack", "postgres", "puppeteer"):
            assert name in MCP_CATALOG

    def test_list_is_sorted_and_described(self) -> None:
        entries = list_mcp_catalog()
        assert [e.name for e in entries] == sorted(e.name for e in entries)
        assert all(e.description for e in entries)


class TestConnect:
    def test_unknown_name_lists_catalog(self) -> None:
        with pytest.raises(ValueError, match="filesystem"):
            connect_mcp("nope")

    def test_missing_env_var_is_caught_up_front(self, monkeypatch) -> None:
        # gitlab is a stdio connector needing a PAT — a missing var is a clear
        # up-front error, not a subprocess failure later.
        monkeypatch.delenv("GITLAB_PERSONAL_ACCESS_TOKEN", raising=False)
        with pytest.raises(ValueError, match="GITLAB_PERSONAL_ACCESS_TOKEN"):
            connect_mcp("gitlab")

    def test_hosted_oauth_requires_a_token(self) -> None:
        # github is now a hosted OAuth connector — it must refuse to run
        # without the user's token rather than call unauthenticated.
        with pytest.raises(ValueError, match="OAuth"):
            connect_mcp("github")

    def test_env_kwarg_satisfies_requirement(self, monkeypatch) -> None:
        monkeypatch.delenv("GITLAB_PERSONAL_ACCESS_TOKEN", raising=False)
        # npx may not exist in CI — accept either success or the launcher error
        try:
            server = connect_mcp("gitlab", env={"GITLAB_PERSONAL_ACCESS_TOKEN": "x"})
        except RuntimeError as err:
            assert "PATH" in str(err)
        else:
            assert isinstance(server, RemoteMCPServer)
            assert server.metadata["catalog"] == "gitlab"

    def test_args_are_appended(self) -> None:
        try:
            server = connect_mcp("filesystem", args=["/tmp/project"])
        except RuntimeError:
            pytest.skip("npx not on PATH")
        assert server.transport.command[-1] == "/tmp/project"

    def test_custom_command_override(self) -> None:
        try:
            server = connect_mcp(
                "filesystem", command=["python", "-m", "my_server"], args=["/x"]
            )
        except RuntimeError:
            pytest.skip("python not on PATH (impossible)")
        assert server.transport.command == ["python", "-m", "my_server", "/x"]
