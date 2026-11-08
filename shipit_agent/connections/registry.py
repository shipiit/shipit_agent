"""Discover what is connectable, and what is actually connected.

Nothing here invents a list. Connectors are discovered from the tools the
agent is holding — each one already carries a ``credential_key`` — and MCP
servers from the catalog. State comes from the credential store. A registry
that maintained its own list would drift from the tools that exist.
"""

from __future__ import annotations

from typing import Any, Iterable

from .discovery import _ConnectionDiscovery
from .models import AuthKind, Connection, ConnectionRequest
from .registry_support import (
    AUTH_KINDS as AUTH_KINDS,
)
from .registry_support import (
    TITLES as TITLES,
)
from .registry_support import (
    title_for as title_for,
)

__all__ = ["ConnectionRegistry", "AUTH_KINDS", "TITLES"]

# How each provider authenticates. Wrong-but-plausible guidance is worse than
# none — "it needs you to sign in" for something that wants a pasted API key
# sends the user looking for a button that does not exist.

# Display names. A user recognizes "Google Sheets", not "google_sheets".

# Credential fields that count as "there is a credential here".


class ConnectionRegistry(_ConnectionDiscovery):
    """The connection state of everything this agent could reach."""

    def __init__(
        self,
        *,
        credential_store: Any = None,
        tools: Iterable[Any] = (),
        mcps: Iterable[Any] = (),
        include_catalog: bool = False,
    ) -> None:
        self.credential_store = credential_store
        self._tools = list(tools)
        self._mcps = list(mcps)
        # The MCP catalog lists servers you *could* install, which is a
        # different question from what this agent can reach. Off by default so
        # "what's connected?" doesn't answer with a shopping list.
        self.include_catalog = include_catalog
        self.requests: list[ConnectionRequest] = []

    # ── discovery ────────────────────────────────────────────────────────

    # ── state resolution ─────────────────────────────────────────────────

    # ── public surface ───────────────────────────────────────────────────

    def all(self) -> list[Connection]:
        """Every connection, resolved, connected first then by title."""
        connections = [
            self._resolve_state(c)
            for c in (*self._connector_connections(), *self._mcp_connections())
        ]
        return sorted(
            connections, key=lambda c: (not c.usable, c.title.lower())
        )

    def get(self, connection_id: str) -> Connection | None:
        wanted = (connection_id or "").strip().lower()
        for connection in self.all():
            if connection.id.lower() == wanted or connection.title.lower() == wanted:
                return connection
        return None

    def connected(self) -> list[Connection]:
        return [c for c in self.all() if c.usable]

    def needing_action(self) -> list[Connection]:
        return [c for c in self.all() if c.needs_action]

    def is_connected(self, connection_id: str) -> bool:
        connection = self.get(connection_id)
        return bool(connection and connection.usable)

    # ── requests ─────────────────────────────────────────────────────────

    def request(self, connection_id: str, reason: str) -> ConnectionRequest:
        """Record that the agent needs a connection it does not have."""
        connection = self.get(connection_id)
        request = ConnectionRequest(
            connection_id=connection_id,
            reason=reason,
            title=connection.title if connection else connection_id,
            auth=connection.auth if connection else AuthKind.UNKNOWN,
        )
        self.requests.append(request)
        return request

    def resolve(
        self,
        connection_id: str,
        *,
        accepted: bool,
        credential: Any = None,
        by: str = "user",
    ) -> ConnectionRequest | None:
        """Answer a pending request — the other half of the UI card.

        On accept with a ``credential``, it is written to the credential store,
        so the very next state check reads ``CONNECTED`` rather than the user
        being told to connect something they just connected. Returns the
        request that was answered, or ``None`` if there was none pending.
        """
        for request in self.pending_requests():
            if request.connection_id != connection_id:
                continue
            request.resolved = True
            request.accepted = accepted
            request.resolved_by = by
            if accepted and credential is not None and self.credential_store:
                self._store_credential(connection_id, credential)
            return request
        return None

    def _store_credential(self, connection_id: str, credential: Any) -> None:
        """Write a credential in whichever shape this store accepts."""
        from shipit_agent.integrations import CredentialRecord

        record = credential
        if isinstance(credential, dict):
            record = CredentialRecord(
                key=connection_id, provider=connection_id, secrets=dict(credential)
            )
        elif not isinstance(credential, CredentialRecord):
            # A bare string is the common case — a pasted API key or token.
            record = CredentialRecord(
                key=connection_id,
                provider=connection_id,
                secrets={"token": str(credential)},
            )
        self.credential_store.set(record)

    def pending_requests(self) -> list[ConnectionRequest]:
        return [r for r in self.requests if not r.resolved]

    # ── rendering ────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        connections = self.all()
        return {
            "total": len(connections),
            "connected": sum(1 for c in connections if c.usable),
            "needs_action": sum(1 for c in connections if c.needs_action),
            "pending_requests": len(self.pending_requests()),
        }

    def render(self, *, only_connected: bool = False) -> str:
        """The listing the agent reads, and the CLI prints."""
        connections = self.connected() if only_connected else self.all()
        if not connections:
            return "No connections are available."
        lines: list[str] = []
        for connection in connections:
            mark = "✓" if connection.usable else "·"
            line = f"  {mark} {connection.describe()}"
            if connection.tools:
                line += f"\n      tools: {', '.join(sorted(connection.tools))}"
            if connection.needs_action:
                line += f"\n      → {connection.next_step()}"
            lines.append(line)
        return "\n".join(lines)
