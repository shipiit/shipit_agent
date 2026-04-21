"""Prebuilt agents — curated AgentDefinitions loadable from JSON."""

from .definition import AgentDefinition
from .registry import AgentRegistry

# Auto-apply the specialist-roster patch so role agents (generalist-developer,
# debugger, design-reviewer, product-manager, sales-outreach, customer-
# success, marketing-writer) are available without the caller remembering
# to import a separate module. The patch is idempotent — running it twice
# is cheap and safe.
from . import _specialists_patch  # noqa: F401

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
]
