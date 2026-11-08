"""How ConnectionRegistry finds connector and MCP connections and resolves their state."""

from __future__ import annotations

import time

from .models import AuthKind, Connection, ConnectionState
from .registry_support import _SECRET_FIELDS, AUTH_KINDS, title_for


class _ConnectionDiscovery:
    """How ConnectionRegistry finds connector and MCP connections and resolves their state."""

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
