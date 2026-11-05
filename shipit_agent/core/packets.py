"""Serialising run events and results for HTTP, WebSocket and SSE clients.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from shipit_agent.core.models import AgentEvent, AgentResult


def event_packet(event: AgentEvent) -> dict[str, Any]:
    """A run event as a JSON-ready dict."""
    return {
        "packet_type": "agent_event",
        "event": event.to_dict(),
    }


def result_packet(result: AgentResult) -> dict[str, Any]:
    """A run result as a JSON-ready dict."""
    return {
        "packet_type": "agent_result",
        "result": result.to_dict(),
    }


def websocket_event_packet(event: AgentEvent) -> dict[str, Any]:
    """A run event shaped for a WebSocket message."""
    return {
        "type": "agent_event",
        "packet_type": "agent_event",
        "event_type": event.type,
        "event": event.to_dict(),
    }


def websocket_result_packet(result: AgentResult) -> dict[str, Any]:
    """A run result shaped for a WebSocket message."""
    return {
        "type": "agent_result",
        "packet_type": "agent_result",
        "result": result.to_dict(),
    }


def sse_event_packet(event: AgentEvent) -> str:
    """A run event as one Server-Sent Events frame."""
    return (
        f"event: {event.type}\ndata: {json.dumps(event.to_dict(), sort_keys=True)}\n\n"
    )


def sse_result_packet(result: AgentResult) -> str:
    """A run result as one Server-Sent Events frame."""
    return (
        f"event: agent_result\ndata: {json.dumps(result.to_dict(), sort_keys=True)}\n\n"
    )


def sse_event_stream(events: Iterable[AgentEvent]) -> list[str]:
    """Every event in *events* as Server-Sent Events frames."""
    return [sse_event_packet(event) for event in events]
