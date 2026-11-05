"""Where compaction may cut: the start of a user turn or of an agent step."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from shipit_agent.core.models import Message

from .tokens import estimate_tokens


def starts_a_turn(message: Message) -> bool:
    """Does this message open an agent turn?

    Cutting anywhere else leaves the retained messages opening mid-turn — a
    dangling tool result with no matching call, which several providers reject
    outright.
    """
    if message.role != "user":
        return False
    # Planner output and compaction summaries are injected as user messages but
    # sit *inside* a turn, so they are not valid cut points.
    source = message.metadata.get("source")
    return source not in ("planner",) and not message.metadata.get("compacted")


def starts_a_step(message: Message) -> bool:
    """Does this message open a model *step* within a turn?

    The hard constraint is that a ``tool`` message must stay with the assistant
    message carrying its tool call — an orphaned tool result is what providers
    reject. Cutting immediately before an assistant message always satisfies
    that, so it is the fallback when no turn start fits.
    """
    return message.role == "assistant"


def find_boundary(
    messages: Sequence[Message],
    target_tokens: int,
    count: Callable[[Any], int] | None = None,
) -> int:
    """Index to start replay from: the newest safe cut that fits the target.

    Prefers a **turn** start, so retained messages open the way a conversation
    does. Falls back to a **step** start (an assistant message), because a long
    single turn — one prompt, thirty tool calls — has no turn boundary to cut
    at, and that is exactly the shape that most needs compacting.

    Returns ``0`` when no cut helps; nothing is compacted rather than cutting
    somewhere a provider will reject.

    ``count`` must be the same per-message counter the caller used to derive
    ``target_tokens``; it defaults to the raw estimate so existing callers are
    unaffected.
    """
    if not messages:
        return 0
    measure = count or (lambda content: estimate_tokens(content))
    running = 0
    turn_boundary = 0
    step_boundary = 0
    for index in range(len(messages) - 1, -1, -1):
        running += measure(messages[index].content or "")
        if running > target_tokens:
            break
        if starts_a_turn(messages[index]):
            turn_boundary = index
        elif starts_a_step(messages[index]):
            step_boundary = index
    return turn_boundary or step_boundary
