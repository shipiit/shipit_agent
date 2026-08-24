"""Per-run state and safe shared-state isolation for tool execution."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.models import AgentEvent, Message, ToolResult


@dataclass(slots=True)
class RuntimeState:
    """Mutable state owned by one agent run."""

    messages: list[Message] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    seen_tool_outputs: dict = field(default_factory=dict)
    last_observation: str = ""
    executed_readonly_calls: set = field(default_factory=set)
    #: tool name -> (consecutive rejected completions, last counted iteration).
    #: Keyed by logical tool name, never by provider call id — a provider mints
    #: a fresh id for every retry, so a per-id counter never reaches its budget.
    tool_argument_rejections: dict = field(default_factory=dict)
    #: Tools whose argument-recovery budget is spent; not advertised again.
    quarantined_tools: set = field(default_factory=set)
    #: Guards the two fields above. Unlike ``shared_state``, this object is
    #: NOT copied per call — the sync loop's thread pool hands the same
    #: instance to every worker in a parallel batch.
    argument_rejection_lock: Any = field(default_factory=threading.Lock)
    verify_gate: Any = None


# Service objects stay shared by reference; ordinary data is isolated per tool.
_SHARED_SERVICE_STATE_KEYS = frozenset({"memory_store", "credential_store"})


def isolated_tool_state(shared_state: dict[str, Any]) -> dict[str, Any]:
    """Copy mutable tool state while retaining shared service references."""
    isolated: dict[str, Any] = {}
    for key, value in shared_state.items():
        if key in _SHARED_SERVICE_STATE_KEYS:
            isolated[key] = value
            continue
        try:
            isolated[key] = copy.deepcopy(value)
        except Exception:  # noqa: BLE001
            isolated[key] = value
    return isolated


def merge_tool_state(target: dict[str, Any], child: dict[str, Any]) -> None:
    """Deterministically merge an isolated tool state into canonical state."""
    for key, value in child.items():
        if key in _SHARED_SERVICE_STATE_KEYS:
            continue
        if key not in target:
            target[key] = value
        elif isinstance(value, list) and isinstance(target.get(key), list):
            existing = target[key]
            for item in value:
                if item not in existing:
                    existing.append(item)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)
        else:
            target[key] = value


# Private aliases retain the existing runtime imports during the transition.
_isolated_tool_state = isolated_tool_state
_merge_tool_state = merge_tool_state
