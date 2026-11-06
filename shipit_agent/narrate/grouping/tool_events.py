"""How the accumulator takes in tool calls: their start, outcome and streamed input,
and the calls a delegated agent makes."""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.core.models import AgentEvent

from .calls import CallRecord, CallStatus
from .rows import SubAgentRow


class ToolEventsMixin:
    """Records each call, matches its outcome to it, and groups a child's calls."""

    _calls: list[CallRecord]
    _by_id: dict[str, CallRecord]
    _group_id: str | None
    writing: dict[str, str]
    _sub_agents: dict[tuple[str, str], SubAgentRow]
    _emitted_sub_agents: dict[tuple[str, str], SubAgentRow]

    # Defined by the accumulator.
    _flush_work: Callable[[], None]
    _flush_prose: Callable[[], None]

    def _on_tool_called(self, event: AgentEvent) -> None:
        payload = event.payload
        # The argument finished streaming; the settled row takes over.
        self.writing.pop(str(payload.get("call_id") or ""), None)
        group = payload.get("group_id")
        if group is not None and group != self._group_id:
            # A new declared group closes the previous one.
            self._flush_work()
            self._group_id = str(group)
        self._flush_prose()
        call = CallRecord(
            call_id=str(payload.get("call_id") or f"call_{len(self._calls)}"),
            name=str(payload.get("tool", "?")),
            arguments=dict(payload.get("arguments") or {}),
            iteration=payload.get("iteration"),
        )
        self._calls.append(call)
        self._by_id[call.call_id] = call

    def _on_tool_denied(self, event: AgentEvent) -> None:
        # A denied call may never have emitted `tool_called` (the gate can
        # fire first), so this is the only place the prose introducing it
        # gets closed.
        self._flush_prose()
        self._on_tool_outcome(event.payload, "denied")

    def _on_tool_completed(self, event: AgentEvent) -> None:
        self._on_tool_outcome(event.payload, "ok")

    def _on_tool_failed(self, event: AgentEvent) -> None:
        self._on_tool_outcome(event.payload, "error")

    def _on_tool_outcome(self, payload: dict[str, Any], status: CallStatus) -> None:
        call = self._resolve(payload)
        if call is None:
            return
        call.duration_ms = _as_float(payload.get("duration_ms"))
        call.status = status
        if status == "ok":
            call.output = str(payload.get("output", "") or "")
        elif status == "error":
            call.error = str(payload.get("error", "") or "")
        else:
            call.error = str(payload.get("reason", "") or "not permitted")

    def _on_tool_input_started(self, event: AgentEvent) -> None:
        payload = event.payload
        self.writing[str(payload.get("call_id") or "")] = ""

    def _on_tool_input_delta(self, event: AgentEvent) -> None:
        payload = event.payload
        key = str(payload.get("call_id") or "")
        self.writing[key] = self.writing.get(key, "") + str(payload.get("delta", ""))

    def _on_sub_agent_event(self, event: AgentEvent) -> None:
        """Accumulate a child's tool calls into one attributed row.

        Only the child's *work* is surfaced. Its prose is its own reasoning,
        and the parent already reports the conclusion — showing both would say
        everything twice.
        """
        payload = event.payload
        if payload.get("inner_type") != "tool_called":
            return
        inner = dict(payload.get("inner") or {})
        agent = str(payload.get("agent") or "sub-agent")
        task = str(payload.get("task") or "")
        tool = str(inner.get("tool") or "?")

        key = (agent, task)
        row = self._sub_agents.get(key) or self._emitted_sub_agents.get(key)
        if row is None:
            row = self._sub_agents[key] = SubAgentRow(agent=agent, task=task)
        row.calls.append(
            CallRecord(
                call_id=str(inner.get("call_id") or f"sub_{len(row.calls)}"),
                name=tool,
                arguments=dict(inner.get("arguments") or {}),
                status="ok",
            )
        )

    def _resolve(self, payload: dict[str, Any]) -> CallRecord | None:
        """Match an outcome to its call — by id, else by the newest running call.

        The id is always present in practice; the fallback covers a
        ``tool_denied`` emitted before its ``tool_called`` (the permission
        gate blocks ahead of the call event) and any adapter that drops it.
        """
        call_id = payload.get("call_id")
        if call_id is not None and str(call_id) in self._by_id:
            return self._by_id[str(call_id)]
        name = payload.get("tool")
        for call in reversed(self._calls):
            if call.status == "running" and (name is None or call.name == name):
                return call
        if name:
            # A gate that fired before the call was announced: synthesize the
            # record so the block still shows up in the transcript.
            call = CallRecord(
                call_id=str(call_id or f"gate_{len(self._calls)}"), name=str(name)
            )
            self._calls.append(call)
            self._by_id[call.call_id] = call
            return call
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
