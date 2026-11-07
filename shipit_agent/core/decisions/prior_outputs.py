"""Keeping earlier turns' tool output out of the prompt, and adding reminders without derailing the model."""

from __future__ import annotations

from copy import deepcopy

from shipit_agent.core.models import Message

#: Below this, the stub costs more than the payload it replaces.
_EVICT_MIN_CHARS = 1_000


def attach_reminder(messages: list[Message], reminder: str) -> list[Message]:
    """Put the reminder last without making it the thing to answer.

    Sent as its own trailing user message, small models answered the
    reminder ("I am ready for your request") instead of the question. When
    the request is the last message, the reminder rides on it — the
    question still leads and nothing separate follows it. After a tool
    result, the result stays put and the reminder follows, labelled.
    """
    note = f"[Reminder — not a new request: {reminder}]"
    last = messages[-1] if messages else None
    if (
        last is not None
        and last.role == "user"
        and isinstance(last.content, str)
        and not (last.metadata or {}).get("internal")
    ):
        merged = deepcopy(last)
        merged.content = f"{last.content}\n\n{note}"
        return [*messages[:-1], merged]
    return [
        *messages,
        Message(
            role="user", content=note, metadata={"internal": True, "kind": "reminder"}
        ),
    ]


def _evicted_notice(message: Message, *, recall_tool_name: str = "") -> str:
    """A compact, factual pointer that does not invite a repeat-call loop."""
    metadata = dict(message.metadata or {})
    call_id = str(message.tool_call_id or metadata.get("tool_call_id") or "")
    path = str(metadata.get("persisted_output_path") or "")
    original_chars = len(message.content) if isinstance(message.content, str) else 0
    details = [
        f"call_id={call_id}" if call_id else "",
        f"original_chars={original_chars}" if original_chars else "",
        f"stored_at={path}" if path else "",
    ]
    suffix = "; ".join(detail for detail in details if detail)
    recall = (
        f" Retrieve the exact result with {recall_tool_name}(call_id={call_id!r}) "
        "only if it is needed."
        if recall_tool_name and call_id
        else ""
    )
    return (
        "[Earlier tool result omitted from the active prompt to save context"
        + (f" ({suffix})" if suffix else "")
        + ". The structured call and the assistant's answer remain above. "
        "Use those first."
        + recall
        + " Rerun the original external tool only when its data may have changed.]"
    )


def evict_prior_tool_outputs(
    messages: list[Message],
    *,
    min_chars: int = _EVICT_MIN_CHARS,
    recall_tool_name: str = "",
) -> list[Message]:
    """Replace tool *payloads* from earlier turns with a short notice.

    A message list is cumulative across turns as well as within one. A search
    that returned fifteen thousand characters in turn one is re-sent, in full,
    on every request of turn two, turn three, and so on — long after the model
    has written whatever mattered into its answer.

    What is kept is the part that stays useful and costs almost nothing: the
    assistant's tool call, with its name and arguments. That is what tells the
    model what it already looked for, so it doesn't look again. What goes is
    the payload, which it has already read.

    The messages themselves are never dropped. A tool result removed while its
    assistant tool-call message remains is a malformed conversation that some
    providers reject outright, so each is replaced in place — same role, same
    name, same ``tool_call_id`` — and only the content changes.

    Small outputs are left alone: below ``min_chars`` the notice is the larger
    of the two.
    """
    evicted: list[Message] = []
    for message in messages:
        if (
            getattr(message, "role", "") == "tool"
            # Block-content messages (images) are never evicted here — they
            # have their own recency-based pruning in step_request, and
            # replacing a list with a text notice would corrupt the shape.
            and isinstance(message.content, str)
            and len(message.content or "") >= min_chars
        ):
            evicted.append(
                Message(
                    role="tool",
                    name=message.name,
                    content=_evicted_notice(message, recall_tool_name=recall_tool_name),
                    tool_call_id=message.tool_call_id,
                    metadata=dict(message.metadata or {}),
                )
            )
        else:
            evicted.append(message)
    return evicted
