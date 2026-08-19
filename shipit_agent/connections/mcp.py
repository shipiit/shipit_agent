"""MCP servers as records, so adding a connection is configuration.

``connections/models.py`` and ``registry.py`` already model a *connection* — its
auth kind, its state, whether the user has connected it. What they do not carry
is how to reach an MCP server: transport, command or URL, which environment
variable holds the token. That is what this adds, alongside rather than instead.

Every connector written as a class is a release cycle between "we need Linear"
and having Linear. So a connector is data. It comes from YAML, a dict, or the
shipped catalog, and all three are the same shape:

```yaml
connections:
  jira:
    transport: sse
    url: https://mcp.atlassian.com/v1/sse
    auth: {kind: bearer, env: JIRA_MCP_TOKEN}
  local-fs:
    use: filesystem          # a catalog template, then override anything
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./src"]
```

Two decisions worth stating:

**Secrets are named, never stored.** A record holds the *name* of an environment
variable. A config file that leaks then leaks a variable name, which is not a
secret. Resolution happens at connect time, and a missing variable is a named,
fixable condition rather than a 401 twenty seconds later.

**Unreachable is a state, not an exception.** ``check()`` returns a verdict for
every connector, so a preflight shows the whole picture at once. Discovering
three missing tokens one failed connection at a time is three times the work.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "Transport",
    "MCPAuthKind",
    "MCPAuth",
    "MCPConnector",
    "MCPConnectorStatus",
    "MCPConnectorRegistry",
    "MCP_CATALOG",
]


class Transport(str, Enum):
    STDIO = "stdio"   # a subprocess speaking JSON-RPC on stdin/stdout
    HTTP = "http"     # a plain HTTP endpoint
    SSE = "sse"       # HTTP with a server-sent-events response channel


class MCPAuthKind(str, Enum):
    """How to authenticate. Distinct from ``models.AuthKind``, which describes
    how a *user* connects an account; this is how a *process* presents a
    credential on the wire."""

    NONE = "none"
    BEARER = "bearer"
    HEADER = "header"
    BASIC = "basic"
    OAUTH = "oauth"   # the transport runs its own flow


@dataclass(frozen=True, slots=True)
class MCPAuth:
    kind: MCPAuthKind = MCPAuthKind.NONE
    env: str = ""
    user_env: str = ""
    header: str = "Authorization"

    def resolve(self) -> tuple[dict[str, str], list[str]]:
        """``(headers, missing)``. Missing names are returned, not raised, so a
        caller can report every gap in one pass."""
        if self.kind is MCPAuthKind.NONE:
            return {}, []

        missing: list[str] = []
        token = os.getenv(self.env, "") if self.env else ""
        if self.env and not token:
            missing.append(self.env)

        if self.kind is MCPAuthKind.BASIC:
            user = os.getenv(self.user_env, "") if self.user_env else ""
            if self.user_env and not user:
                missing.append(self.user_env)
            if missing:
                return {}, missing
            encoded = base64.b64encode(f"{user}:{token}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}, []

        if missing:
            return {}, missing
        if self.kind is MCPAuthKind.BEARER:
            return {"Authorization": f"Bearer {token}"}, []
        if self.kind is MCPAuthKind.HEADER:
            return {self.header: token}, []
        return {}, []


@dataclass(frozen=True, slots=True)
class MCPConnectorStatus:
    name: str
    state: str          # ready | missing_credentials | missing_binary | misconfigured | disabled
    advice: str = ""
    missing: Sequence[str] = ()

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"name": self.name, "state": self.state}
        if self.advice:
            row["advice"] = self.advice
        if self.missing:
            row["missing"] = list(self.missing)
        return row


@dataclass(frozen=True, slots=True)
class MCPConnector:
    """One reachable MCP server, described rather than implemented."""

    name: str
    transport: Transport = Transport.STDIO
    command: Sequence[str] = ()
    url: str = ""
    auth: MCPAuth = field(default_factory=MCPAuth)
    env_passthrough: Sequence[str] = ()
    #: Hold this server's tools behind ``tool_search`` regardless of size.
    deferred: bool = False
    enabled: bool = True
    description: str = ""
    timeout_seconds: int = 30

    # -- checks ------------------------------------------------------------

    def missing_credentials(self) -> list[str]:
        return self.auth.resolve()[1]

    def missing_binary(self) -> str:
        if self.transport is not Transport.STDIO or not self.command:
            return ""
        return "" if shutil.which(self.command[0]) else self.command[0]

    def check(self) -> MCPConnectorStatus:
        """A verdict without connecting. Cheap enough for every startup."""
        if not self.enabled:
            return MCPConnectorStatus(self.name, "disabled", "Disabled in configuration.")

        missing = self.missing_credentials()
        if missing:
            return MCPConnectorStatus(
                self.name,
                "missing_credentials",
                f"Set {', '.join(missing)} to use this connector.",
                missing=missing,
            )

        binary = self.missing_binary()
        if binary:
            return MCPConnectorStatus(
                self.name,
                "missing_binary",
                f"{binary!r} is not on PATH. Install it, or correct the command.",
            )

        if self.transport is Transport.STDIO and not self.command:
            return MCPConnectorStatus(
                self.name, "misconfigured", "No command set for a stdio connector."
            )
        if self.transport is not Transport.STDIO and not self.url:
            return MCPConnectorStatus(
                self.name, "misconfigured", "No url set for an HTTP connector."
            )

        return MCPConnectorStatus(self.name, "ready")

    # -- materialisation ---------------------------------------------------

    def connection_kwargs(self) -> dict[str, Any]:
        """Everything a transport needs, with credentials resolved.

        A plain dict, so this stays independent of whichever transport
        implementation is in use — and so a resolved token exists only for the
        moment of connecting rather than living on an object.
        """
        headers, missing = self.auth.resolve()
        if missing:
            raise RuntimeError(
                f"Connector {self.name!r} needs {', '.join(missing)}; none set."
            )
        payload: dict[str, Any] = {
            "name": self.name,
            "transport": self.transport.value,
            "timeout": self.timeout_seconds,
        }
        if self.transport is Transport.STDIO:
            payload["command"] = list(self.command)
            payload["env"] = {
                key: os.environ[key] for key in self.env_passthrough if key in os.environ
            }
        else:
            payload["url"] = self.url
            payload["headers"] = headers
        return payload

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "MCPConnector":
        auth_data: Any = data.get("auth") or {}
        if isinstance(auth_data, str):
            auth_data = {"kind": auth_data}
        auth = MCPAuth(
            kind=MCPAuthKind(str(auth_data.get("kind", "none"))),
            env=str(auth_data.get("env", "")),
            user_env=str(auth_data.get("user_env", "")),
            header=str(auth_data.get("header", "Authorization")),
        )
        command = data.get("command") or ()
        if isinstance(command, str):
            command = command.split()
        return cls(
            name=name,
            transport=Transport(str(data.get("transport", "stdio"))),
            command=tuple(str(part) for part in command),
            url=str(data.get("url", "")),
            auth=auth,
            env_passthrough=tuple(data.get("env_passthrough") or ()),
            deferred=bool(data.get("deferred", False)),
            enabled=bool(data.get("enabled", True)),
            description=str(data.get("description", "")),
            timeout_seconds=int(data.get("timeout_seconds", 30)),
        )


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


class MCPConnectorRegistry:
    """The MCP servers a deployment has, and what state each is in."""

    def __init__(self, connectors: Iterable[MCPConnector] = ()) -> None:
        self._connectors: dict[str, MCPConnector] = {c.name: c for c in connectors}

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "MCPConnectorRegistry":
        """Build from a mapping. ``use:`` names a catalog template to override."""
        registry = cls()
        for name, data in (config or {}).items():
            if not isinstance(data, Mapping):
                continue
            template = MCP_CATALOG.get(str(data.get("use", "")), {})
            merged = {**template, **{k: v for k, v in data.items() if k != "use"}}
            try:
                registry.add(MCPConnector.from_dict(str(name), merged))
            except (ValueError, KeyError) as error:
                # One bad entry must not cost the others.
                logger.warning("Ignoring connector %s: %s", name, error)
        return registry

    @classmethod
    def from_catalog(cls, *names: str) -> "MCPConnectorRegistry":
        return cls(
            MCPConnector.from_dict(name, MCP_CATALOG[name])
            for name in names
            if name in MCP_CATALOG
        )

    def add(self, connector: MCPConnector) -> "MCPConnectorRegistry":
        self._connectors[connector.name] = connector
        return self

    def __iter__(self):
        return iter(sorted(self._connectors.values(), key=lambda c: c.name))

    def __len__(self) -> int:
        return len(self._connectors)

    def get(self, name: str) -> MCPConnector | None:
        return self._connectors.get(name)

    def ready(self) -> list[MCPConnector]:
        return [c for c in self if c.check().ready]

    def deferred_names(self) -> list[str]:
        return sorted(c.name for c in self if c.deferred)

    def report(self) -> dict[str, Any]:
        """The whole picture at once, for a preflight."""
        statuses = [c.check() for c in self]
        return {
            "total": len(statuses),
            "ready": sum(1 for s in statuses if s.ready),
            "deferred": self.deferred_names(),
            "problems": [s.to_dict() for s in statuses if not s.ready],
        }
