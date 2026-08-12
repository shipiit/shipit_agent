"""The run as a **timeline** — the event shape a frontend actually wants.

:meth:`Agent.stream` is the runtime's own vocabulary: every text delta, every
retry, every partial argument. That is the right feed for a renderer and the
wrong one for a UI, which wants to draw four things — a summary of what the
agent set out to do, groups of tool calls, the decisions between them, and the
final answer.

This module translates one into the other::

    for step in stream_timeline(agent, "Process the latest RSVP"):
        socket.send(json.dumps(step))

    # {"type": "run_started",         "goal": "Process the latest RSVP"}
    # {"type": "tool_group_started",  "group_id": "g1", "title": "Reading 2 files"}
    # {"type": "tool_call_started",   "tool_call_id": "1", "tool_name": "read_file", …}
    # {"type": "tool_call_completed", "tool_call_id": "1", "status": "completed", …}
    # {"type": "tool_group_completed","group_id": "g1", "title": "Read 2 files"}
    # {"type": "agent_decision",      "content": "…", "next_action": "call_tool"}
    # {"type": "final_response",      "content": "…", "tool_calls": 4}

Three properties it is built to hold:

**Causal.** Every step is emitted from information that already exists. A
group's settled title arrives in ``tool_group_completed``, not retroactively
patched into the ``started`` event — a client that has already drawn a row
never has to undraw it.

**JSON, not objects.** Every step is a plain dict of primitives, so it goes
onto a socket, into a log, or through :mod:`shipit_agent.streaming` unchanged.

**No hidden reasoning.** ``agent_decision`` carries the prose the model
actually emitted between tool calls — the same text a user sees in the
transcript. Nothing private is exposed, because nothing private is read.

:func:`render_markdown` prints the same timeline as a report, for a PR comment
or a run log.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator

from shipit_agent.models import AgentEvent

from .verbs import summarize

__all__ = [
    "TimelineBuilder",
    "render_markdown",
    "stream_timeline",
    "timeline",
]

_NEXT_ACTION = {
    "tool": "call_tool",
    "ask": "ask_user",
    "finish": "finish",
}

_NOTICES = {
    "context_compacted": "Older turns were condensed to stay in the context window",
    "guardrail_triggered": "A guardrail stopped the run",
    "lockdown_engaged": "Lockdown — sensitive data was read, so only read-only "
    "tools may run for the rest of this run",
    "run_cancelled": "Cancelled",
}


class TimelineBuilder:
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
        kind = event.type
        out: list[dict[str, Any]] = []

        if kind == "run_started":
            return [{"type": "run_started", "goal": str(payload.get("prompt") or "")}]

        if kind in ("planning_completed", "reasoning_completed"):
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

        if kind == "text_delta":
            chunk = str(payload.get("chunk", ""))
            if chunk:
                # Prose closes a group — the same rule the transcript uses.
                if not self._group_declared:
                    out += self._close_group()
                self._prose.append(chunk)
            return out

        if kind == "tool_group_started":
            out += self._close_prose(next_action="tool")
            out += self._open_declared_group(payload)
            return out

        if kind == "tool_called":
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

        if kind in ("tool_completed", "tool_failed", "tool_denied"):
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

        if kind == "action_queued":
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

        if kind in ("agent_decision", "agent_observation"):
            summary = str(payload.get("summary") or event.message or "").strip()
            if not summary:
                return out
            phase = str(payload.get("phase") or "").strip().lower()
            if kind == "agent_observation":
                phase = "observation"
            elif phase not in ("decision", "observation"):
                phase = "decision"
            # The runtime generated this one, so it is preferred over the
            # decision this builder would otherwise infer from prose.
            self._prose = []
            out += self._close_group()
            return out + [
                {
                    "type": "agent_decision",
                    "phase": phase,
                    "content": summary,
                    "next_action": str(payload.get("next_action") or ""),
                    "iteration": payload.get("iteration"),
                    "generated_by_model": bool(payload.get("generated_by_model")),
                }
            ]

        if kind == "artifact_created":
            return out + [
                {
                    "type": "artifact_created",
                    "path": str(payload.get("path") or ""),
                    "title": str(payload.get("title") or ""),
                    "kind": str(payload.get("kind") or "File"),
                    "tool": str(payload.get("tool") or ""),
                }
            ]

        if kind == "connection_requested":
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

        if kind == "sub_agent_event":
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

        if kind == "usage_tick":
            self._usage = dict(payload.get("usage") or {})
            return out

        if kind == "run_completed":
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


# ── markdown report ──────────────────────────────────────────────────────


def render_markdown(
    source: Iterable[AgentEvent] | Any,
    *,
    goal: str | None = None,
    title: str = "Agent Run",
    output_limit: int = 1200,
) -> str:
    """The same timeline as a readable report.

    Sections are numbered as they happened — tool groups, decisions, and the
    final answer — with each call's input and result as JSON blocks. Good for
    a PR comment, a run log, or a notebook cell.
    """
    steps = timeline(source)
    lines: list[str] = [f"## {title}", ""]

    goal = goal or next(
        (s.get("goal") for s in steps if s["type"] == "run_started"), None
    )
    if goal:
        lines += [f"**Goal:** {goal}", "", "---", ""]

    section = 0
    calls: dict[str, dict[str, Any]] = {}
    total_ms = 0.0

    for step in steps:
        kind = step["type"]
        if kind == "reasoning_summary":
            section += 1
            lines += [
                f"### {section}. Understanding the request",
                "",
                str(step["content"]),
                "",
                "**Status:** Completed",
                "",
                "---",
                "",
            ]
        elif kind == "tool_group_started":
            section += 1
            lines += [f"### {section}. Tool calls", "", f"#### {step['title']}", ""]
        elif kind == "tool_call_started":
            calls[str(step["tool_call_id"])] = step
            lines += [f"##### `{step['tool_name']}`", ""]
            if step["input"]:
                lines += ["**Input**", "", "```json", _dump(step["input"]), "```", ""]
        elif kind == "tool_call_completed":
            total_ms += float(step.get("duration_ms") or 0)
            lines += [
                f"**Status:** {str(step['status']).capitalize()}  ",
                f"**Duration:** {step.get('duration_ms', 0):.0f} ms",
                "",
            ]
            body = step.get("output", step.get("error", ""))
            if body not in ("", None):
                lines += [
                    "**Result**",
                    "",
                    "```json",
                    _dump(body)[:output_limit],
                    "```",
                    "",
                ]
        elif kind == "tool_group_completed":
            lines += ["---", ""]
        elif kind == "artifact_created":
            lines += [f"📎 **{step['title']}** — {step['kind']} · `{step['path']}`", ""]
        elif kind == "agent_observation" or (
            kind == "agent_decision" and step.get("phase") == "observation"
        ):
            section += 1
            lines += [
                f"### {section}. Observation",
                "",
                str(step["content"]),
                "",
                "---",
                "",
            ]
        elif kind == "agent_decision":
            section += 1
            lines += [
                f"### {section}. Agent decision",
                "",
                str(step["content"]),
                "",
                f"**Next action:** {step['next_action']}",
                "",
                "---",
                "",
            ]
        elif kind == "approval_required":
            section += 1
            lines += [
                f"### {section}. Approval required",
                "",
                f"{step['title']} — `{step.get('tag') or step['tool_name']}`",
                "",
                "---",
                "",
            ]
        elif kind == "connection_required":
            section += 1
            lines += [
                f"### {section}. Connection required",
                "",
                f"**{step['title']}** — {step['reason']}",
                "",
                f"`{step['connection_id']}` · {step['auth']}",
                "",
                "---",
                "",
            ]
        elif kind == "sub_agent_tool_call":
            lines += [
                f"- **{step['agent']}** ran `{step['tool_name']}` "
                f"— {step['task'][:80]}",
                "",
            ]
        elif kind == "notice":
            lines += [f"> {step['content']}", ""]
        elif kind == "final_response":
            section += 1
            lines += [
                f"### {section}. Final response",
                "",
                str(step["content"]),
                "",
                "**Run status:** Successful  ",
                f"**Tool calls:** {step['tool_calls']}  ",
                f"**Total tool duration:** {total_ms / 1000:.2f} seconds",
                "",
            ]
            usage = step.get("usage") or {}
            tokens = int(usage.get("total_tokens") or 0)
            if tokens:
                lines.append(f"**Tokens:** {tokens:,}")
    return "\n".join(lines).rstrip() + "\n"


def _dump(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default= covers it
        return str(value)


def _jsonable(value: Any) -> Any:
    """Keep structure when it is already JSON, fall back to text when not.

    A tool's output is usually a string; when it happens to be JSON, a UI can
    render it as a table rather than a blob, so it is worth parsing.
    """
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    text = str(value)
    stripped = text.strip()
    if stripped[:1] in ("{", "[") and stripped[-1:] in ("}", "]"):
        try:
            return json.loads(stripped)
        except ValueError:
            return text
    return text


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
