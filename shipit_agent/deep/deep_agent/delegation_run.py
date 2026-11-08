"""Running one sub-agent for the delegation tool, and naming it."""

from __future__ import annotations

from typing import Any


def _agent_name(agent: Any, fallback: str) -> str:
    """Resolve a friendly name for an agent passed via ``agents=``."""
    for attr in ("name", "agent_name"):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = getattr(agent, "agent", None)
    if inner is not None:
        for attr in ("name", "agent_name"):
            value = getattr(inner, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _agent_description(agent: Any) -> str:
    for attr in ("description", "agent_description"):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = getattr(agent, "agent", None)
    if inner is not None:
        value = getattr(inner, "description", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{agent.__class__.__name__} sub-agent"


def _run_agent(
    agent: Any,
    task: str,
    *,
    capture_events: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Invoke any kind of inner agent and return ``(text, metadata)``.

    When ``capture_events`` is True the inner agent's ``stream()`` method
    is used (when available) so events flow into ``metadata['events']``,
    letting the parent surface what the sub-agent did. Falls back to
    ``run()`` if the inner agent has no ``stream()``.
    """
    metadata: dict[str, Any] = {}
    text: str | None = None

    if capture_events and hasattr(agent, "stream"):
        captured_events: list[dict[str, Any]] = []
        try:
            stream_iter = agent.stream(task)
        except TypeError:
            stream_iter = agent.stream()
        for event in stream_iter:
            captured_events.append(
                {
                    "type": getattr(event, "type", ""),
                    "message": getattr(event, "message", ""),
                    "payload": dict(getattr(event, "payload", {}) or {}),
                }
            )
            if getattr(event, "type", "") == "run_completed":
                payload = getattr(event, "payload", {}) or {}
                if isinstance(payload, dict) and payload.get("output"):
                    text = payload["output"]
        metadata["events"] = captured_events
        if text is not None:
            return text, metadata

    if hasattr(agent, "run"):
        try:
            result = agent.run(task)
        except TypeError:
            # Some deep agents (GoalAgent) take no prompt at run time.
            result = agent.run()
        text = getattr(result, "output", None)
        if text is None:
            text = str(result)
        metadata.update(dict(getattr(result, "metadata", {}) or {}))
        sources = getattr(result, "rag_sources", None)
        if sources:
            metadata["rag_sources"] = [
                src.to_dict() if hasattr(src, "to_dict") else src for src in sources
            ]
        return text, metadata
    raise TypeError(f"Sub-agent {agent.__class__.__name__} has no run() method")

