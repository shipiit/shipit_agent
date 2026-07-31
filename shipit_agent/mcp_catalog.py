"""Prebuilt MCP catalog — one line to a well-known MCP server.

Instead of hand-writing transport commands, connect by name::

    from shipit_agent import Agent, connect_mcp

    github = connect_mcp("github")           # needs GITHUB_TOKEN in env
    files  = connect_mcp("filesystem", args=["/my/project"])
    agent  = Agent.with_builtins(llm=llm, mcps=[github, files])

Each entry runs the official server over stdio (via ``npx``/``uvx``) with a
persistent subprocess, and declares which env vars it needs so failures are
caught up front with a clear message instead of a cryptic subprocess error.
Browse the catalog with :func:`list_mcp_catalog`.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from .mcp import PersistentMCPSubprocessTransport, RemoteMCPServer


@dataclass(slots=True)
class MCPCatalogEntry:
    name: str
    description: str
    command: list[str]
    required_env: list[str] = field(default_factory=list)
    accepts_args: bool = False  # extra positional args (e.g. filesystem roots)


_NPX = ["npx", "-y"]

MCP_CATALOG: dict[str, MCPCatalogEntry] = {
    entry.name: entry
    for entry in [
        MCPCatalogEntry(
            name="filesystem",
            description="Read/write files under the directories you pass as args.",
            command=[*_NPX, "@modelcontextprotocol/server-filesystem"],
            accepts_args=True,
        ),
        MCPCatalogEntry(
            name="github",
            description="Repos, issues, PRs, code search on GitHub.",
            command=[*_NPX, "@modelcontextprotocol/server-github"],
            required_env=["GITHUB_TOKEN"],
        ),
        MCPCatalogEntry(
            name="gitlab",
            description="GitLab projects, issues, and merge requests.",
            command=[*_NPX, "@modelcontextprotocol/server-gitlab"],
            required_env=["GITLAB_PERSONAL_ACCESS_TOKEN"],
        ),
        MCPCatalogEntry(
            name="slack",
            description="Post and read Slack messages and channels.",
            command=[*_NPX, "@modelcontextprotocol/server-slack"],
            required_env=["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        ),
        MCPCatalogEntry(
            name="postgres",
            description="Query PostgreSQL (read-only). Pass the connection URL as an arg.",
            command=[*_NPX, "@modelcontextprotocol/server-postgres"],
            accepts_args=True,
        ),
        MCPCatalogEntry(
            name="sqlite",
            description="Query a SQLite database file passed as an arg.",
            command=["uvx", "mcp-server-sqlite", "--db-path"],
            accepts_args=True,
        ),
        MCPCatalogEntry(
            name="playwright",
            description="Official Playwright MCP: navigate, click, type, screenshot via accessibility tree.",
            command=[*_NPX, "@playwright/mcp@latest"],
        ),
        MCPCatalogEntry(
            name="puppeteer",
            description="Headless browser: navigate, screenshot, interact with pages.",
            command=[*_NPX, "@modelcontextprotocol/server-puppeteer"],
        ),
        MCPCatalogEntry(
            name="brave-search",
            description="Web search via the Brave Search API.",
            command=[*_NPX, "@modelcontextprotocol/server-brave-search"],
            required_env=["BRAVE_API_KEY"],
        ),
        MCPCatalogEntry(
            name="fetch",
            description="Fetch a URL and return page content as markdown.",
            command=["uvx", "mcp-server-fetch"],
        ),
        MCPCatalogEntry(
            name="memory",
            description="Persistent knowledge-graph memory across runs.",
            command=[*_NPX, "@modelcontextprotocol/server-memory"],
        ),
        MCPCatalogEntry(
            name="sentry",
            description="Look up Sentry issues and stack traces.",
            command=["uvx", "mcp-server-sentry", "--auth-token"],
            required_env=["SENTRY_AUTH_TOKEN"],
        ),
        MCPCatalogEntry(
            name="google-maps",
            description="Places, directions, and geocoding via Google Maps.",
            command=[*_NPX, "@modelcontextprotocol/server-google-maps"],
            required_env=["GOOGLE_MAPS_API_KEY"],
        ),
    ]
}


def list_mcp_catalog() -> list[MCPCatalogEntry]:
    """All prebuilt MCP servers, alphabetically."""
    return [MCP_CATALOG[k] for k in sorted(MCP_CATALOG)]


def connect_mcp(
    name: str,
    *,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    command: list[str] | None = None,
) -> RemoteMCPServer:
    """Connect to a well-known MCP server by catalog name.

    Validates required env vars and the launcher binary up front, then
    returns a :class:`RemoteMCPServer` on a persistent stdio transport —
    pass it straight to ``Agent(..., mcps=[...])``. ``args`` appends
    positional arguments (filesystem roots, connection URLs); ``env``
    supplies/overrides environment variables; ``command`` replaces the
    launch command entirely (e.g. a local build).
    """
    entry = MCP_CATALOG.get(name)
    if entry is None:
        known = ", ".join(sorted(MCP_CATALOG))
        raise ValueError(f"Unknown MCP server '{name}'. Catalog: {known}")

    merged_env = {**(env or {})}
    missing = [
        var
        for var in entry.required_env
        if not (merged_env.get(var) or os.environ.get(var))
    ]
    if missing:
        raise ValueError(
            f"MCP server '{name}' needs env var(s): {', '.join(missing)}. "
            "Pass them via env={...} or export them."
        )

    full_command = list(command or entry.command)
    if args:
        full_command += [str(a) for a in args]
    launcher = full_command[0]
    if shutil.which(launcher) is None:
        raise RuntimeError(
            f"'{launcher}' is not on PATH — install it to run the "
            f"'{name}' MCP server (npx ships with Node.js; uvx with uv)."
        )

    transport = PersistentMCPSubprocessTransport(full_command, env=merged_env)
    return RemoteMCPServer(
        name=name,
        transport=transport,
        metadata={"catalog": name, "description": entry.description},
    )
