"""Code mode — a small `env` of capabilities instead of 50 tool schemas.

Stage 4 of the modern-agent upgrade (``docs/design/modern-agent-upgrade.md``).
See :mod:`shipit_agent.codemode.bindings` for the rationale.
"""

from .bindings import (
    Binding,
    BindingMethod,
    binding_name_for,
    build_binding,
    build_bindings,
)
from .bridge import BridgeCall, BridgeLimits, BridgeServer
from .catalog import (
    CatalogEntry,
    ResourceCatalog,
    load_catalog,
    normalize_catalog,
)

__all__ = [
    "Binding",
    "BridgeCall",
    "BridgeLimits",
    "BridgeServer",
    "BindingMethod",
    "CatalogEntry",
    "ResourceCatalog",
    "binding_name_for",
    "build_binding",
    "build_bindings",
    "load_catalog",
    "normalize_catalog",
]
