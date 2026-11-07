"""What each runtime event becomes in the timeline."""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.core.models import AgentEvent

from .values import _as_float, _jsonable

_NOTICES = {
    "context_compacted": "Older turns were condensed to stay in the context window",
    "context_compaction_started": "Context automatically compacting",
    "guardrail_triggered": "A guardrail stopped the run",
    "lockdown_engaged": "Lockdown — sensitive data was read, so only read-only "
    "tools may run for the rest of this run",
    "run_cancelled": "Cancelled",
}


class TimelineEventsMixin:
    """One handler per event kind; each returns the steps the event produced."""

    _group: str | None
    _group_calls: list[dict[str, Any]]
    _group_declared: bool
    _prose: list[str]
    _calls: int
    _usage: dict[str, Any]
    # Defined by the builder.
    _close_group: Callable[[], list[dict[str, Any]]]
    _close_prose: Callable[..., list[dict[str, Any]]]
    _open_group: Callable[[dict[str, Any]], list[dict[str, Any]]]
    _open_declared_group: Callable[[dict[str, Any]], list[dict[str, Any]]]

    def _on_run_started(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"type": "run_started", "goal": str(payload.get("prompt") or "")}]

    def _on_reasoning(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        content = str(
            payload.get("summary")
            or payload.get("plan")
            or payload.get("output")
            or ""
        ).strip()
        if content:
            out.append(
                {
                    "type": "reasoning_summary",
                    "status": "completed",
                    "content": content,
                }
            )
        return out

    def _on_text_delta(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        chunk = str(payload.get("chunk", ""))
        if chunk:
            # Prose closes a group — the same rule the transcript uses.
            if not self._group_declared:
                out += self._close_group()
            self._prose.append(chunk)
        return out

    def _on_tool_group_started(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        out += self._close_prose(next_action="tool")
        out += self._open_declared_group(payload)
        return out

    def _on_tool_called(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        # A tool call closes any prose before it, and that prose *is* the
        # decision that led here.
        out += self._close_prose(next_action="tool")
        out += self._open_group(payload)
        self._calls += 1
        call_id = str(payload.get("call_id") or self._calls)
        call = {
            "type": "tool_call_started",
            "tool_call_id": call_id,
            "group_id": self._group,
            "tool_name": str(payload.get("tool") or "?"),
            "input": _jsonable(payload.get("arguments") or {}),
        }
        if not any(existing.get("id") == call_id for existing in self._group_calls):
            self._group_calls.append(
                {
                    "tool": call["tool_name"],
                    "id": call["tool_call_id"],
                    "arguments": call["input"],
                }
            )
        out.append(call)
        return out

    def _on_tool_outcome(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        status = {
            "tool_completed": "completed",
            "tool_failed": "failed",
            "tool_denied": "denied",
        }[kind]
        step: dict[str, Any] = {
            "type": "tool_call_completed",
            "tool_call_id": str(payload.get("call_id") or self._calls),
            "group_id": self._group,
            "tool_name": str(payload.get("tool") or "?"),
            "status": status,
            "duration_ms": _as_float(payload.get("duration_ms")),
        }
        if status == "completed":
            step["output"] = _jsonable(payload.get("output"))
        else:
            step["error"] = str(payload.get("error") or payload.get("reason") or "")
        return [step]

    def _on_action_queued(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        out += self._close_group()
        out += self._close_prose(next_action="ask")
        return out + [
            {
                "type": "approval_required",
                "action_id": payload.get("action_id"),
                "tool_name": str(payload.get("tool") or "?"),
                "title": str(payload.get("title") or payload.get("tool") or ""),
                "tag": payload.get("tag"),
                "auto_approved": bool(payload.get("auto_approved")),
            }
        ]
        return out

    def _on_decision(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        summary = str(payload.get("summary") or event.message or "").strip()
        if not summary:
            return out
        # The runtime generated this one, so it is preferred over the
        # decision this builder would otherwise infer from prose.
        self._prose = []
        out += self._close_group()
        return out + [
            {
                "type": kind,
                "content": summary,
                "next_action": str(payload.get("next_action") or ""),
                "iteration": payload.get("iteration"),
                "generated_by_model": bool(payload.get("generated_by_model")),
            }
        ]
        return out

    def _on_artifact_created(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        return out + [
            {
                "type": "artifact_created",
                "path": str(payload.get("path") or ""),
                "title": str(payload.get("title") or ""),
                "kind": str(payload.get("kind") or "File"),
                "tool": str(payload.get("tool") or ""),
            }
        ]
        return out

    def _on_connection_requested(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        out += self._close_group()
        out += self._close_prose(next_action="ask")
        return out + [
            {
                "type": "connection_required",
                "connection_id": str(payload.get("connection_id") or ""),
                "title": str(payload.get("title") or ""),
                "reason": str(payload.get("reason") or ""),
                "auth": str(payload.get("auth") or "unknown"),
            }
        ]
        return out

    def _on_sub_agent_event(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        inner = dict(payload.get("inner") or {})
        if payload.get("inner_type") != "tool_called":
            return out
        return [
            {
                "type": "sub_agent_tool_call",
                "agent": str(payload.get("agent") or "sub-agent"),
                "task": str(payload.get("task") or ""),
                "tool_name": str(inner.get("tool") or "?"),
                "input": _jsonable(inner.get("arguments") or {}),
            }
        ]
        return out

    def _on_usage_tick(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        self._usage = dict(payload.get("usage") or {})
        return out

    def _on_run_completed(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        self._usage = dict(payload.get("usage") or self._usage)
        out += self._close_group()
        content = "".join(self._prose).strip() or str(
            payload.get("output", "") or ""
        )
        self._prose = []
        out.append(
            {
                "type": "final_response",
                "status": "completed",
                "content": content,
                "tool_calls": self._calls,
                "usage": _jsonable(self._usage),
            }
        )
        return out

    def _on_notice(self, event: AgentEvent, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        notice = _NOTICES.get(kind)
        if notice:
            out += self._close_group()
            detail = payload.get("reason") or payload.get("message")
            return out + [
                {
                    "type": "notice",
                    "kind": kind,
                    "content": f"{notice}: {detail}" if detail else notice,
                }
            ]
        return out
