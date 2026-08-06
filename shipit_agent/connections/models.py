"""What a connection is, and what state it is in.

shipit already had the pieces — 17 connectors each holding a
``credential_key``, a ``CredentialStore``, OAuth helpers, an MCP catalog — but
nothing tied them together. There was no way to ask "what can I connect?",
"what *is* connected?", or "why did that call fail?". A connector with no
credential just returned a string saying so, mid-run, as a tool result.

Cloudflare OS treats connecting as a first-class flow: list what is
connectable, request a connection, watch it turn green. The card in their UI —
*BigQuery — analytics.usage · ✓ Connected* — is the visible half of a state
machine. This is that state machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["AuthKind", "ConnectionState", "Connection", "ConnectionRequest"]


class AuthKind(str, Enum):
    """How a connection is authenticated — which decides how to fix it."""

    OAUTH = "oauth"          # a browser round-trip
    API_KEY = "api_key"      # a secret the user pastes
    TOKEN = "token"          # a personal access token
    NONE = "none"            # nothing needed (a local MCP server, say)
    UNKNOWN = "unknown"


class ConnectionState(str, Enum):
    """Where a connection stands.

    ``EXPIRED`` is deliberately distinct from ``DISCONNECTED``: the difference
    is "reconnect this" versus "set this up", and telling a user to set up
    something they already configured is how trust in a status display dies.
    """

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    NEEDS_AUTH = "needs_auth"    # configured, but the credential is missing
    EXPIRED = "expired"          # was connected; the token has run out
    ERROR = "error"              # configured and failing for another reason

    @property
    def usable(self) -> bool:
        return self is ConnectionState.CONNECTED


@dataclass(slots=True)
class Connection:
    """One connectable resource and its current state."""

    id: str                      # the credential key / MCP server name
    title: str                   # what a human calls it
    kind: str = "connector"      # "connector" | "mcp"
    state: ConnectionState = ConnectionState.DISCONNECTED
    auth: AuthKind = AuthKind.UNKNOWN
    description: str = ""
    account: str = ""            # which account, when known
    tools: tuple[str, ...] = ()  # tool names this connection powers
    error: str = ""
    expires_at: float | None = None
    checked_at: float = field(default_factory=time.time)

    # ── derived ──────────────────────────────────────────────────────────

    @property
    def usable(self) -> bool:
        return self.state.usable

    @property
    def needs_action(self) -> bool:
        """Would a human have to do something to make this work?"""
        return self.state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.NEEDS_AUTH,
            ConnectionState.EXPIRED,
        )

    def next_step(self) -> str:
        """What the user would have to do — phrased as an instruction."""
        if self.state is ConnectionState.CONNECTED:
            return ""
        if self.state is ConnectionState.EXPIRED:
            return f"Reconnect {self.title} — its credential has expired."
        if self.state is ConnectionState.ERROR:
            return f"{self.title} is failing: {self.error or 'unknown error'}"
        if self.auth is AuthKind.OAUTH:
            return f"Connect {self.title} — it needs you to sign in."
        if self.auth in (AuthKind.API_KEY, AuthKind.TOKEN):
            noun = "an API key" if self.auth is AuthKind.API_KEY else "a token"
            return f"Connect {self.title} — it needs {noun}."
        return f"Connect {self.title}."

    def describe(self) -> str:
        """One line, in the transcript's voice."""
        mark = {
            ConnectionState.CONNECTED: "connected",
            ConnectionState.EXPIRED: "expired",
            ConnectionState.NEEDS_AUTH: "needs authentication",
            ConnectionState.DISCONNECTED: "not connected",
            ConnectionState.ERROR: "error",
        }[self.state]
        line = f"{self.title} — {mark}"
        if self.account:
            line += f" ({self.account})"
        return line

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "state": self.state.value,
            "auth": self.auth.value,
            "description": self.description,
            "account": self.account,
            "tools": list(self.tools),
            "usable": self.usable,
            "needs_action": self.needs_action,
            "next_step": self.next_step(),
            "error": self.error,
        }


@dataclass(slots=True)
class ConnectionRequest:
    """The agent asking for a connection it needs but does not have.

    Deliberately not an exception. A missing connection is a thing the *user*
    resolves, so it belongs in the transcript as a request with a reason,
    not as a stack trace the model tries to work around.
    """

    connection_id: str
    reason: str
    title: str = ""
    auth: AuthKind = AuthKind.UNKNOWN
    requested_at: float = field(default_factory=time.time)
    resolved: bool = False

    def describe(self) -> str:
        name = self.title or self.connection_id
        return f"Requested a connection to {name}: {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "title": self.title,
            "reason": self.reason,
            "auth": self.auth.value,
            "resolved": self.resolved,
        }
