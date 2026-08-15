"""Connectors — one clean module per integration, one call to attach it.

    from shipit_agent import Agent
    from shipit_agent.connectors import connect, list_connectors

    linear = connect("linear", token=user_token)   # hosted, per-user OAuth
    slack  = connect("slack")                       # stdio, env token
    agent  = Agent.with_builtins(llm=llm, mcps=[linear, slack])

Browse the catalog with ``list_connectors()`` / ``list_connectors(category=…)``.
Each connector is declared in its own module under ``catalog/`` as a
:class:`Connector` manifest and self-registers on import.
"""

from __future__ import annotations

from .base import Connector
from .oauth_manager import (
    NeedsReconnect,
    NotConnected,
    OAuthCredentialManager,
)
from .registry import (
    connect,
    connector_categories,
    get_connector,
    list_connectors,
    register,
)
from .tokens import FileTokenStore, InMemoryTokenStore, TokenStore

__all__ = [
    "Connector",
    "FileTokenStore",
    "InMemoryTokenStore",
    "NeedsReconnect",
    "NotConnected",
    "OAuthCredentialManager",
    "TokenStore",
    "connect",
    "connector_categories",
    "get_connector",
    "list_connectors",
    "register",
]
