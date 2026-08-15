"""Backwards-compatible surface over the connector catalog.

The catalog now lives in :mod:`shipit_agent.connectors` — one clean directory
per connector, each a declarative ``manifest.yaml``. This module keeps the
older ``connect_mcp`` / ``list_mcp_catalog`` names working; new code should
prefer ``from shipit_agent.connectors import connect, list_connectors``.
"""

from __future__ import annotations

from .connectors import Connector as MCPCatalogEntry  # noqa: F401 — compat alias
from .connectors import connect as connect_mcp  # noqa: F401
from .connectors import connector_categories as mcp_catalog_categories  # noqa: F401
from .connectors import list_connectors as _list_connectors
from .connectors.registry import get_connector  # noqa: F401


def list_mcp_catalog(*, category: str | None = None) -> list[MCPCatalogEntry]:
    """All prebuilt connectors, alphabetically (optionally one category)."""
    return _list_connectors(category=category)


class _LazyCatalog:
    """A dict-like view over the connector registry — ``name in MCP_CATALOG``,
    iteration and lookup — without forcing a catalog load at import time."""

    def _all(self) -> dict[str, MCPCatalogEntry]:
        return {c.name: c for c in _list_connectors()}

    def __contains__(self, name: object) -> bool:
        return get_connector(str(name)) is not None

    def __getitem__(self, name: str) -> MCPCatalogEntry:
        c = get_connector(name)
        if c is None:
            raise KeyError(name)
        return c

    def get(self, name: str, default=None):
        return get_connector(name) or default

    def __iter__(self):
        return iter(self._all())

    def __len__(self) -> int:
        return len(_list_connectors())

    def keys(self):
        return self._all().keys()

    def values(self):
        return self._all().values()

    def items(self):
        return self._all().items()


#: Backwards-compatible lazy view of the catalog (prefer ``list_connectors``).
MCP_CATALOG = _LazyCatalog()


__all__ = [
    "MCP_CATALOG",
    "MCPCatalogEntry",
    "connect_mcp",
    "get_connector",
    "list_mcp_catalog",
    "mcp_catalog_categories",
]
