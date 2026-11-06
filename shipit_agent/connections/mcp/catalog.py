"""Ready-made connectors for well-known MCP servers, used by name."""

from __future__ import annotations

from typing import Any

#: Shipped shapes for servers people commonly connect. Endpoints and package
#: names change, so these are starting points to copy and override — which is
#: the whole reason a connector is data rather than a class.
MCP_CATALOG: dict[str, dict[str, Any]] = {
    "filesystem": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
        "description": "Read and write files under a directory.",
    },
    "git": {
        "transport": "stdio",
        "command": ["uvx", "mcp-server-git", "--repository", "."],
        "description": "Inspect history, diffs and branches.",
    },
    "github": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "auth": {"kind": "bearer", "env": "GITHUB_PERSONAL_ACCESS_TOKEN"},
        "env_passthrough": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "description": "Issues, pull requests and repository contents.",
    },
    "postgres": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-postgres"],
        "env_passthrough": ["DATABASE_URL"],
        "deferred": True,
        "description": "Query a Postgres database read-only.",
    },
    "slack": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-slack"],
        "auth": {"kind": "bearer", "env": "SLACK_BOT_TOKEN"},
        "env_passthrough": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "deferred": True,
        "description": "Read and post messages.",
    },
    "sentry": {
        "transport": "sse",
        "url": "https://mcp.sentry.dev/sse",
        "auth": {"kind": "oauth"},
        "deferred": True,
        "description": "Inspect issues and stack traces.",
    },
    "memory": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"],
        "description": "A persistent knowledge graph across runs.",
    },
    "fetch": {
        "transport": "stdio",
        "command": ["uvx", "mcp-server-fetch"],
        "description": "Fetch a URL and convert it to markdown.",
    },
}
