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
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            connect_mcp("github")

    def test_env_kwarg_satisfies_requirement(self, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        # npx may not exist in CI — accept either success or the launcher error
        try:
            server = connect_mcp("github", env={"GITHUB_TOKEN": "x"})
        except RuntimeError as err:
            assert "PATH" in str(err)
        else:
            assert isinstance(server, RemoteMCPServer)
            assert server.metadata["catalog"] == "github"

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
