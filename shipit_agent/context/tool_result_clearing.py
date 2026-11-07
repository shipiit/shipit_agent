"""Clearing old tool results from the request, so a long task stops paying for them.

Every turn re-sends the whole conversation. On a long task that means paying,
turn after turn, for files read twenty turns ago and long since acted on.
Anthropic offers server-side clearing for this; this does the same on the
client, so it works with every provider.

The rules:

- Nothing happens until the uncleared tool results in a request exceed
  ``trigger_tokens``.
- Then the oldest are replaced by a one-line note naming the tool and its
  main argument, so the model can call it again if it needs the content.
  The ``keep`` most recent results always stay whole, and results too small
  to matter, or from ``exclude_tools``, are left alone.
- Clearing goes down to half the trigger, and the clearing point never moves
  back. The request's prefix therefore changes only once per batch, and a
  provider's prompt cache keeps hitting between batches.
- Only the request is changed. The stored history keeps every result.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from shipit_agent.core.models import Message

__all__ = ["ToolResultClearing", "clear_old_tool_results"]

#: The argument that best names what a call looked at, by preference.
_NAMING_ARGUMENTS = ("path", "file_path", "pattern", "query", "command", "url")


@dataclass(frozen=True)
class ToolResultClearing:
    """When and how to clear old tool results from each request."""

    #: Uncleared tool-result tokens in a request that start a clearing batch.
    trigger_tokens: int = 30_000
    #: The most recent tool results that always stay whole.
    keep: int = 3
    #: Results smaller than this are left alone: clearing them saves nothing.
    min_result_tokens: int = 100
    #: Tools whose results are never cleared.
    exclude_tools: tuple[str, ...] = ()

    @classmethod
    def from_setting(cls, setting: "ToolResultClearing | bool | None") -> "ToolResultClearing | None":
        """``True`` → the defaults; ``None`` or ``False`` → off; a policy → itself."""
        if setting is True:
            return cls()
        if not setting:
            return None
        return setting


def clear_old_tool_results(
    messages: Sequence[Message],
    policy: ToolResultClearing,
    count_tokens: Callable[[str], int],
    *,
    state: str | None,
) -> tuple[list[Message], str | None]:
    """The request view with old results cleared, and the new clearing state.

    *state* is the call id of the last result earlier requests cleared
    (``None`` for the first); pass back what this returns, so the point only
    advances. An id, not a count: once compaction drops older messages, a
    count would point at newer results. If that result is gone, the count
    starts again from the results that remain.
    """
    eligible = [i for i, m in enumerate(messages)
                if m.role == "tool" and (m.name or "") not in policy.exclude_tools]
    candidates = eligible[: max(0, len(eligible) - max(policy.keep, 1))]
    sizes = {i: count_tokens(_text(messages[i])) for i in eligible}
    ids = [messages[i].tool_call_id for i in candidates]
    boundary = ids.index(state) + 1 if state in ids else 0
    remaining = sum(sizes[i] for i in eligible[boundary:])
    if remaining > policy.trigger_tokens:
        while boundary < len(candidates) and remaining > policy.trigger_tokens // 2:
            index = candidates[boundary]
            if sizes[index] >= policy.min_result_tokens:
                remaining -= sizes[index]
            boundary += 1
    marker = ids[boundary - 1] if boundary else state
    cleared = {i for i in candidates[:boundary] if sizes[i] >= policy.min_result_tokens}
    if not cleared:
        return list(messages), marker
    calls = {call.id: call for m in messages if m.role == "assistant" for call in m.tool_calls}
    view = [
        _cleared(message, calls.get(message.tool_call_id or "")) if index in cleared else message
        for index, message in enumerate(messages)
    ]
    return view, marker


def _text(message: Message) -> str:
    return message.content if isinstance(message.content, str) else str(message.content)


def _cleared(message: Message, call: object | None) -> Message:
    name = message.name or getattr(call, "name", "") or "tool"
    arguments = dict(getattr(call, "arguments", {}) or {})
    target = next((str(arguments[k]) for k in _NAMING_ARGUMENTS if arguments.get(k)), "")
    about = f" for {target[:80]}" if target else ""
    note = f"[Earlier {name} result{about} cleared to save context. Call it again if you need it.]"
    return replace(message, content=note, metadata={**message.metadata, "cleared": True})
