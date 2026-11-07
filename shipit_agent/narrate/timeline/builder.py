"""TimelineBuilder: runtime events in, UI steps out."""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from shipit_agent.core.models import AgentEvent

from ..verbs import summarize
from .events import TimelineEventsMixin

_NEXT_ACTION = {
    "tool": "call_tool",
    "ask": "ask_user",
    "finish": "finish",
}

#: Event type → its handler. Anything else may be a notice.
_HANDLERS = {
    "run_started": "_on_run_started",
    "planning_completed": "_on_reasoning",
    "reasoning_completed": "_on_reasoning",
    "text_delta": "_on_text_delta",
    "tool_group_started": "_on_tool_group_started",
    "tool_called": "_on_tool_called",
    "tool_completed": "_on_tool_outcome",
    "tool_failed": "_on_tool_outcome",
    "tool_denied": "_on_tool_outcome",
    "action_queued": "_on_action_queued",
    "agent_decision": "_on_decision",
    "agent_observation": "_on_decision",
    "artifact_created": "_on_artifact_created",
    "connection_requested": "_on_connection_requested",
    "sub_agent_event": "_on_sub_agent_event",
    "usage_tick": "_on_usage_tick",
    "run_completed": "_on_run_completed",
}


class TimelineBuilder(TimelineEventsMixin):
    """Runtime events in, UI steps out.

    Feed events with :meth:`feed` (which returns the steps that event
    produced) and call :meth:`finish` at the end. Stateless between runs —
    build a new one per run.
    """

    def __init__(self) -> None:
        self._group: str | None = None
        self._group_calls: list[dict[str, Any]] = []
        self._group_title: str = ""
        self._group_declared: bool = False
        self._prose: list[str] = []
        self._groups = 0
        self._calls = 0
        self._usage: dict[str, Any] = {}
        self._started: float | None = None
        self._last_ts: float | None = None

    # ── ingest ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> list[dict[str, Any]]:
        payload = dict(event.payload or {})
        handler = getattr(self, _HANDLERS.get(event.type, "_on_notice"))
        return handler(event, event.type, payload)

    def finish(self) -> list[dict[str, Any]]:
        """Close anything still open — for a run that ended without a
        ``run_completed`` (cancelled, or an exception on the way out)."""
        return self._close_group() + self._close_prose(next_action="finish")

    # ── grouping ─────────────────────────────────────────────────────────

    def _open_group(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if self._group is not None:
            return []
        self._group = str(payload.get("group_id") or self._next_group_id())
        self._group_declared = payload.get("group_id") is not None
        self._group_title = summarize(
            str(payload.get("tool") or "?"), dict(payload.get("arguments") or {})
        ).present_label()
        return [
            {
                "type": "tool_group_started",
                "group_id": self._group,
                "title": self._group_title,
                "tools": list(self._group_calls),
            }
        ]

    def _close_group(self) -> list[dict[str, Any]]:
        if self._group is None:
            return []
        step = {
            "type": "tool_group_completed",
            "group_id": self._group,
            "title": self._group_title,
            "tool_calls": len(self._group_calls),
            "tools": list(self._group_calls),
        }
        self._group = None
        self._group_calls = []
        self._group_title = ""
        self._group_declared = False
        return [step]

    def _open_declared_group(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out = self._close_group()
        self._group = str(payload.get("group_id") or self._next_group_id())
        self._group_declared = True
        self._group_calls = [
            {
                "tool": str(tool.get("name") or tool.get("tool") or "?"),
                "id": str(tool.get("call_id") or tool.get("id") or ""),
            }
            for tool in list(payload.get("tools") or [])
        ]
        self._group_title = str(payload.get("title") or "").strip()
        if not self._group_title:
            if len(self._group_calls) == 1:
                self._group_title = str(self._group_calls[0].get("tool") or "?")
            else:
                self._group_title = f"{len(self._group_calls)} tool calls"
        out.append(
            {
                "type": "tool_group_started",
                "group_id": self._group,
                "title": self._group_title,
                "tools": list(self._group_calls),
            }
        )
        return out

    def _next_group_id(self) -> str:
        self._groups += 1
        return f"g{self._groups}"

    def _close_prose(self, *, next_action: str) -> list[dict[str, Any]]:
        text = "".join(self._prose).strip()
        self._prose = []
        if not text:
            return []
        return [
            {
                "type": "agent_decision",
                "content": text,
                "next_action": _NEXT_ACTION.get(next_action, next_action),
            }
        ]


def timeline(source: Iterable[AgentEvent] | Any) -> list[dict[str, Any]]:
    """A finished run's events → the UI timeline."""
    builder = TimelineBuilder()
    steps: list[dict[str, Any]] = []
    for event in getattr(source, "events", source):
        steps += builder.feed(event)
    return steps + builder.finish()


def stream_timeline(agent: Any, prompt: str) -> Iterator[dict[str, Any]]:
    """Run *agent* and yield UI steps as they happen::

    for step in stream_timeline(agent, prompt):
        await websocket.send_json(step)
    """
    builder = TimelineBuilder()
    try:
        for event in agent.stream(prompt):
            yield from builder.feed(event)
    finally:
        yield from builder.finish()
