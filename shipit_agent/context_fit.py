"""Provider-safe final fitting of the exact request sent to an LLM."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Sequence

from shipit_agent.models import Message


def _is_real_user(message: Message) -> bool:
    return (
        message.role == "user"
        and not (message.metadata or {}).get("internal")
        and not (message.metadata or {}).get("compacted")
    )


def _copy_with_content(message: Message, content: str) -> Message:
    return replace(message, content=content, metadata=dict(message.metadata or {}))


def bounded_text(text: str, limit: int, *, label: str) -> str:
    """Keep useful head/tail context and make every omission explicit."""
    if len(text) <= limit:
        return text
    limit = max(128, limit)
    marker = (
        f"\n\n[... {len(text) - limit:,} characters of {label} omitted to fit "
        "the provider context window ...]\n\n"
    )
    if limit <= len(marker) + 32:
        return text[:limit]
    body = limit - len(marker)
    head = int(body * 0.7)
    return text[:head] + marker + text[-(body - head) :]


def fit_messages(
    messages: Sequence[Message],
    *,
    fits: Callable[[Sequence[Message]], bool],
) -> tuple[list[Message], dict[str, int]]:
    """Keep the latest turn atomically and fill remaining space with recent turns.

    The function is tokenizer-agnostic: the caller supplies ``fits`` using its
    provider/model budget. It never leaves a leading tool result because older
    context is admitted only as complete user-turn groups.
    """
    original = list(messages)
    if fits(original):
        return original, {"dropped_messages": 0, "reduced_messages": 0}

    latest_user = next(
        (i for i in range(len(original) - 1, -1, -1) if _is_real_user(original[i])),
        max(0, len(original) - 1),
    )
    systems = [
        message for message in original[:latest_user] if message.role == "system"
    ]
    summaries = [
        message
        for message in original[:latest_user]
        if (message.metadata or {}).get("compacted")
    ]
    summary = summaries[-1:]  # newest progressive summary only
    tail = list(original[latest_user:])

    # A giant current-turn tool payload must not make an otherwise valid
    # session fail. Reduce the largest tool results first, iteratively.
    reduced = 0
    while not fits([*systems, *summary, *tail]):
        candidates = [
            (len(message.content), i)
            for i, message in enumerate(tail)
            if message.role == "tool"
            and isinstance(message.content, str)
            and len(message.content) > 512
        ]
        if not candidates:
            break
        _size, index = max(candidates)
        current = str(tail[index].content)
        next_limit = max(512, len(current) // 2)
        tail[index] = _copy_with_content(
            tail[index], bounded_text(current, next_limit, label="tool result")
        )
        reduced += 1

    # If the latest user supplied an enormous pasted document, preserve the
    # request's beginning and end rather than allowing a provider overflow.
    if not fits([*systems, *summary, *tail]) and tail:
        first = tail[0]
        if isinstance(first.content, str) and len(first.content) > 1024:
            current = first.content
            while len(current) > 1024 and not fits([*systems, *summary, *tail]):
                current = bounded_text(
                    current, max(1024, len(current) // 2), label="user input"
                )
                tail[0] = _copy_with_content(first, current)
                reduced += 1

    # Build complete older user-turn groups, excluding system/summary rows.
    older = [
        message
        for message in original[:latest_user]
        if message.role != "system" and not (message.metadata or {}).get("compacted")
    ]
    groups: list[list[Message]] = []
    current_group: list[Message] = []
    for message in older:
        if _is_real_user(message):
            if current_group:
                groups.append(current_group)
            current_group = [message]
        elif current_group:
            current_group.append(message)
    if current_group:
        groups.append(current_group)

    kept: list[list[Message]] = []
    for group in reversed(groups):
        candidate_groups = [group, *kept]
        candidate = [*systems, *summary]
        for item in candidate_groups:
            candidate.extend(item)
        candidate.extend(tail)
        if not fits(candidate):
            break
        kept = candidate_groups

    fitted = [*systems, *summary]
    for group in kept:
        fitted.extend(group)
    fitted.extend(tail)
    return fitted, {
        "dropped_messages": max(0, len(original) - len(fitted)),
        "reduced_messages": reduced,
    }


__all__ = ["bounded_text", "fit_messages"]
