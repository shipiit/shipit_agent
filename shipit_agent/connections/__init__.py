"""Connections — what the agent can reach, and what it needs from you.

See :mod:`shipit_agent.connections.models` for the state machine and
:mod:`shipit_agent.connections.registry` for how state is resolved.
"""

from .models import AuthKind, Connection, ConnectionRequest, ConnectionState
from .registry import AUTH_KINDS, TITLES, ConnectionRegistry, title_for

__all__ = [
    "AUTH_KINDS",
    "AuthKind",
    "Connection",
    "ConnectionRegistry",
    "ConnectionRequest",
    "ConnectionState",
    "TITLES",
    "title_for",
]
