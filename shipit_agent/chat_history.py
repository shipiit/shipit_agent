"""The collapsed chat-history shape, and the conversions to/from the wire.

Today a turn that used tools is *stored* as three rows — an assistant message
carrying the calls, one ``role="tool"`` message per result, then the assistant's
prose — and their pairing is an invariant the runtime enforces. The *collapsed*
shape stores one message per turn with the result living ON the call
(:class:`~shipit_agent.models.ToolCallPart`), so a call and its result are one
object that no partial write, compaction boundary, or truncation can separate.
That impossibility is the whole reason a request-patching workaround
(``modify_params``) is never needed.

Storage shape and wire shape are deliberately different things. These are the
pure functions that move between them — no runtime change, provable in isolation:

* :func:`collapse` — old (wire) shape → new (collapsed) shape.
* :func:`expand`   — new → old. The rollback path, and the property that makes
  the migration safe to run: ``expand(collapse(x)) == x`` for well-formed
  history.
* :func:`to_wire_messages` — collapsed → the provider's dict shape, generated at
  request time.

The subtle rule is the **incomplete call**: a run paused for approval holds a
call with no output. Serialising its ``tool_calls`` entry without a matching
result recreates the exact provider rejection this shape exists to stop, so an
incomplete call emits nothing on the wire.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from shipit_agent.models import Message, TextPart, ToolCall, ToolCallPart

__all__ = ["collapse", "expand", "to_wire_messages", "is_collapsed"]


def is_collapsed(message: Message) -> bool:
    """True if this message is in the collapsed shape (holds a ToolCallPart)."""
    return isinstance(message.content, list) and any(
        isinstance(part, ToolCallPart) for part in message.content
    )


def collapse(messages: Sequence[Message]) -> list[Message]:
    """Old (wire) shape → collapsed. Idempotent on already-collapsed turns.

    An assistant message that carries tool calls absorbs the ``role="tool"``
    messages that immediately follow it into :class:`ToolCallPart`s. Every other
    message is passed through untouched. An unpaired result (a tool message with
    no matching call) is kept as-is rather than dropped — losing history is worse
    than an odd-looking row.
    """
    out: list[Message] = []
    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]
        if is_collapsed(m):
            out.append(m)
            i += 1
            continue
        if m.role == "assistant" and m.tool_calls:
            # Gather the contiguous run of tool results that answer this turn.
            results: dict[str, Message] = {}
            j = i + 1
            while j < n and messages[j].role == "tool":
                tm = messages[j]
                if tm.tool_call_id:
                    results[tm.tool_call_id] = tm
                j += 1
            parts: list[Any] = [
                TextPart(
                    text=m.content if isinstance(m.content, str) else m.text,
                    tool_call_ids=[c.id for c in m.tool_calls],
                )
            ]
            for call in m.tool_calls:
                tm = results.pop(call.id, None)
                if tm is None:
                    # Incomplete — paused for approval or still in flight.
                    parts.append(
                        ToolCallPart(id=call.id, name=call.name, args=dict(call.arguments))
                    )
                    continue
                meta = dict(tm.metadata)
                parts.append(
                    ToolCallPart(
                        id=call.id,
                        name=call.name,
                        args=dict(call.arguments),
                        output=tm.content if isinstance(tm.content, str) else tm.text,
                        is_error=bool(meta.get("is_error", False)),
                        truncated=bool(meta.get("truncated", False)),
                        duration_ms=float(meta.get("duration_ms", 0.0) or 0.0),
                        metadata=meta,
                    )
                )
            out.append(
                Message(role="assistant", content=parts, name=m.name,
                        metadata=dict(m.metadata))
            )
            i = j
        else:
            out.append(m)
            i += 1
    return out


def _calls_and_text(message: Message) -> tuple[str, list[ToolCallPart]]:
    text = "".join(
        p.text for p in message.content if isinstance(p, TextPart)
    )
    calls = [p for p in message.content if isinstance(p, ToolCallPart)]
    return text, calls


def expand(messages: Sequence[Message]) -> list[Message]:
    """Collapsed shape → old (wire) shape. Inverse of :func:`collapse`.

    Each collapsed turn becomes an assistant message carrying ``tool_calls``
    followed by one ``role="tool"`` message per *completed* call. An incomplete
    call emits no tool message — a ``tool_calls`` entry with no matching result
    is exactly what providers reject.
    """
    out: list[Message] = []
    for m in messages:
        if not is_collapsed(m):
            out.append(m)
            continue
        text, calls = _calls_and_text(m)
        out.append(
            Message(
                role=m.role,
                content=text,
                name=m.name,
                tool_calls=[
                    ToolCall(name=c.name, arguments=dict(c.args), id=c.id)
                    for c in calls
                ],
                metadata=dict(m.metadata),
            )
        )
        for c in calls:
            if not c.complete:
                continue
            out.append(
                Message(
                    role="tool",
                    # An empty string is a valid, completed tool result.  Do
                    # not rewrite it as a failure merely because it is falsy.
                    content=(c.output if c.output is not None
                             else f"{c.name} failed."),
                    tool_call_id=c.id,
                    name=c.name,
                    metadata=dict(c.metadata),
                )
            )
    return out


def to_wire_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Collapsed (or mixed) history → the provider's dict shape.

    Generated on every request, never stored, so storage and wire can differ
    without either being wrong. A plain string message is passed straight
    through; a collapsed turn is expanded to an assistant entry with
    ``tool_calls`` plus one tool entry per completed call.
    """
    wire: list[dict[str, Any]] = []
    for m in messages:
        if not is_collapsed(m):
            wire.append({"role": m.role, "content": m.content})
            continue
        text, calls = _calls_and_text(m)
        # Only COMPLETE calls go on the wire: a tool_calls entry with no matching
        # tool message is exactly the orphan providers reject, so a call still
        # awaiting approval / in flight is omitted here (it re-appears once its
        # result exists). `expand` keeps incomplete calls; the wire must not.
        ready = [c for c in calls if c.complete]
        assistant: dict[str, Any] = {"role": m.role, "content": text}
        if ready:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.args, sort_keys=True),
                    },
                }
                for c in ready
            ]
        wire.append(assistant)
        for c in ready:
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": c.id,
                    "content": (c.output if c.output is not None
                                else f"{c.name} failed."),
                }
            )
    return wire
