"""The set of connectors a run may use, built from config or the catalog."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from .catalog import MCP_CATALOG
from .connector import MCPConnector

logger = logging.getLogger("shipit_agent.connections.mcp")


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
