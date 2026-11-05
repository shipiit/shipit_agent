"""Estimating how many tokens messages will take, without calling a tokenizer."""

from __future__ import annotations

from typing import Any, Sequence

from shipit_agent.core.models import Message

from .limits import TRIGGER_RATIO


def estimate_tokens(text: Any) -> int:
    """Rough token count — ~4 characters per token for English prose.

    Deliberately an estimate: an exact count needs the provider's tokenizer,
    which we cannot assume is installed. This stays a PURE function; the known
    error in it is corrected at the decision point, not here. Dense JSON tool
    output runs ~2.5–3 chars/token, so ``chars/4`` under-counts a tool-heavy
    run — which is the shape that most needs compacting. A
    :class:`~shipit_agent.token_calibration.TokenCalibrator`, fed each
    completion's real ``prompt_tokens``, learns that per-model ratio and the
    ``Compactor`` scales this estimate by it, so under-counting no longer means
    compacting late (which would overflow the provider, not merely run long).

    Block-shaped content (multimodal turns) is costed as its text parts
    plus a flat ~1,500 tokens per image — the right order of magnitude for
    every provider, which is all a compaction trigger needs.
    """
    if isinstance(text, list):
        total = 0
        for block in text:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "image":
                total += 1_500
            else:
                total += len(str(block.get("text", ""))) // 4
        return total
    return len(text) // 4 if text else 0


def messages_tokens(messages: Sequence[Message]) -> int:
    """Estimated token count of *messages*."""
    return sum(estimate_tokens(m.content or "") for m in messages)


def content_tokens(content: Any, model: str | None = None) -> int:
    """Tokens in one message's content — real count when one is obtainable.

    ``estimate_tokens`` is ``chars/4``, and its own docstring notes that dense
    JSON runs 2.5–3 chars/token, so a tool-heavy run is under-counted by the
    better part of half. The calibrator corrects that after a few completions,
    but the first turns of every run are uncorrected, and the clamp means it can
    only ever raise a too-low estimate *later*.

    A real per-model tokenizer removes the error at the source. It is optional
    (it needs LiteLLM's tables), so this degrades to the estimate rather than
    depending on it — the same shape as LibreChat's tokenizer, which falls back
    to ``chars/4`` whenever an encoding is missing.
    """
    if isinstance(content, list):
        # Multimodal blocks: a tokenizer cannot see pixels, and the flat
        # per-image allowance is already the right order of magnitude.
        return estimate_tokens(content)
    from shipit_agent.context.token_counting import count_tokens

    return count_tokens(content or "", model)


def count_messages(messages: Sequence[Message], model: str | None = None) -> int:
    """Token count across a message list, real when available.

    Every consumer of a token count — the compaction trigger, the retention
    boundary walk, and the calibrator's estimate — must go through this one
    function. If they disagree on units, the trigger fires against one number
    while the boundary is chosen against another, and the retained context
    silently misses its target.
    """
    return sum(content_tokens(m.content or "", model) for m in messages)


def should_compact(context_tokens: int, input_budget: int) -> bool:
    """Has the prompt grown enough to compact before the next model call?"""
    return context_tokens >= input_budget * TRIGGER_RATIO
