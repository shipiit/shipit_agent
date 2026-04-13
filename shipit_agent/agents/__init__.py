"""Prebuilt agents — curated AgentDefinitions loadable from JSON."""

from .definition import AgentDefinition
from .registry import AgentRegistry

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
]
