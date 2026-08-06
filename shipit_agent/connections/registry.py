"""Discover what is connectable, and what is actually connected.

Nothing here invents a list. Connectors are discovered from the tools the
agent is holding — each one already carries a ``credential_key`` — and MCP
servers from the catalog. State comes from the credential store. A registry
that maintained its own list would drift from the tools that exist.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from .models import AuthKind, Connection, ConnectionRequest, ConnectionState

__all__ = ["ConnectionRegistry", "AUTH_KINDS", "TITLES"]

# How each provider authenticates. Wrong-but-plausible guidance is worse than
# none — "it needs you to sign in" for something that wants a pasted API key
# sends the user looking for a button that does not exist.
AUTH_KINDS: dict[str, AuthKind] = {
    "gmail": AuthKind.OAUTH,
    "google_calendar": AuthKind.OAUTH,
    "google_drive": AuthKind.OAUTH,
    "google_sheets": AuthKind.OAUTH,
    "slack": AuthKind.OAUTH,
    "salesforce": AuthKind.OAUTH,
    "linkedin": AuthKind.OAUTH,
    "github": AuthKind.TOKEN,
    "gitlab": AuthKind.TOKEN,
    "figma": AuthKind.TOKEN,
    "notion": AuthKind.TOKEN,
    "linear": AuthKind.API_KEY,
    "jira": AuthKind.API_KEY,
    "confluence": AuthKind.API_KEY,
    "stripe": AuthKind.API_KEY,
    "zendesk": AuthKind.API_KEY,
    "custom_api": AuthKind.API_KEY,
}

# Display names. A user recognizes "Google Sheets", not "google_sheets".
TITLES: dict[str, str] = {
    "gmail": "Gmail",
    "google_calendar": "Google Calendar",
    "google_drive": "Google Drive",
    "google_sheets": "Google Sheets",
    "slack": "Slack",
    "linear": "Linear",
    "jira": "Jira",
    "notion": "Notion",
    "confluence": "Confluence",
    "github": "GitHub",
    "gitlab": "GitLab",
    "figma": "Figma",
    "salesforce": "Salesforce",
    "stripe": "Stripe",
    "zendesk": "Zendesk",
    "linkedin": "LinkedIn",
    "custom_api": "Custom API",
}

# Credential fields that count as "there is a credential here".
_SECRET_FIELDS = ("api_key", "token", "access_token", "password", "secret")


def title_for(key: str) -> str:
    return TITLES.get(key) or key.replace("_", " ").title()


class ConnectionRegistry:
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

    def _connector_connections(self) -> list[Connection]:
        by_key: dict[str, Connection] = {}
        for tool in self._tools:
            key = getattr(tool, "credential_key", None)
            if not key:
                continue
            existing = by_key.get(key)
            tool_name = str(getattr(tool, "name", "") or "")
            if existing is not None:
                # Several tools can share one credential (the Google family).
                existing.tools = (*existing.tools, tool_name)
                continue
            by_key[key] = Connection(
                id=key,
                title=title_for(key),
                kind="connector",
                auth=AUTH_KINDS.get(key, AuthKind.UNKNOWN),
                description=str(getattr(tool, "description", "") or "")[:200],
                tools=(tool_name,) if tool_name else (),
            )
        return list(by_key.values())

    def _mcp_connections(self) -> list[Connection]:
        connections: list[Connection] = []
        for mcp in self._mcps:
            name = str(getattr(mcp, "name", "") or "mcp")
            # An attached MCP server is reachable by definition — it was
            # constructed and handed to the agent. Whether its *transport* is
            # alive is a different question, answered by refresh().
            connections.append(
                Connection(
                    id=name,
                    title=name.replace("_", " ").title(),
                    kind="mcp",
                    state=ConnectionState.CONNECTED,
                    auth=AuthKind.NONE,
                    description=str(getattr(mcp, "description", "") or ""),
                )
            )

        if self.include_catalog:
            from shipit_agent.mcp_catalog import MCP_CATALOG

            attached = {c.id for c in connections}
            for name, entry in MCP_CATALOG.items():
                if name in attached:
                    continue
                needs_env = bool(getattr(entry, "env", None))
                connections.append(
                    Connection(
                        id=name,
                        title=name.replace("_", " ").title(),
                        kind="mcp",
                        state=ConnectionState.DISCONNECTED,
                        auth=AuthKind.API_KEY if needs_env else AuthKind.NONE,
                        description=str(getattr(entry, "description", "") or ""),
                    )
                )
        return connections

    # ── state resolution ─────────────────────────────────────────────────

    def _resolve_state(self, connection: Connection) -> Connection:
        """Fill in the real state from the credential store."""
        if connection.kind == "mcp":
            return connection
        if self.credential_store is None:
            # No store means no credentials can exist. Saying "needs auth"
            # here would be wrong — nothing is configured at all.
            connection.state = ConnectionState.DISCONNECTED
            return connection

        try:
            record = self.credential_store.get(connection.id)
        except Exception as exc:  # noqa: BLE001
            connection.state = ConnectionState.ERROR
            connection.error = str(exc)
            return connection

        if record is None:
            connection.state = ConnectionState.DISCONNECTED
            return connection

        secrets = dict(getattr(record, "secrets", {}) or {})
        metadata = dict(getattr(record, "metadata", {}) or {})
        connection.account = str(
            metadata.get("account") or metadata.get("email") or ""
        )

        if not any(secrets.get(f) for f in _SECRET_FIELDS):
            # A record exists but carries nothing to authenticate with — the
            # user started setting this up and did not finish.
            connection.state = ConnectionState.NEEDS_AUTH
            return connection

        expires_at = metadata.get("expires_at") or getattr(record, "expires_at", None)
        if expires_at:
            try:
                connection.expires_at = float(expires_at)
                if connection.expires_at <= time.time():
                    connection.state = ConnectionState.EXPIRED
                    return connection
            except (TypeError, ValueError):
                pass

        connection.state = ConnectionState.CONNECTED
        return connection

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
