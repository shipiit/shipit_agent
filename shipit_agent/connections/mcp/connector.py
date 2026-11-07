"""One MCP connector: its transport, auth, readiness check and connection settings."""

from __future__ import annotations

import base64
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class Transport(str, Enum):
    """How an MCP server is reached: a stdio subprocess or HTTP."""
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
    """How this process presents a credential to an MCP server: none, bearer token, header, basic auth or OAuth.
    """
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
    """Whether an MCP connector is ready, missing credentials or missing its command."""
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
