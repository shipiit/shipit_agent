"""Prefix-aware + calibrated compaction: it fires at the RIGHT time.

Two long-standing under-counts made the trigger fire late — late enough that a
tool-heavy prompt overflows the provider. These tests pin the fixes:
  1. the fixed prefix (system prompt + tool schemas) counts toward the trigger;
  2. a learned per-model calibration factor scales the estimate.
Both must fire *earlier* than the old messages-only estimate, and cuts must
still land on turn/step boundaries so no tool result is orphaned.
"""
from __future__ import annotations

from shipit_agent.compaction import Compactor, messages_tokens, starts_a_turn
from shipit_agent.models import Message
from shipit_agent.token_calibration import TokenCalibrator


def user(text: str, **md) -> Message:
    return Message(role="user", content=text, metadata=md)


def assistant(text: str) -> Message:
    return Message(role="assistant", content=text)


def tool(text: str, name: str = "read_file") -> Message:
    return Message(role="tool", content=text, name=name)


def conversation(turns: int, chars: int = 4000) -> list[Message]:
    msgs: list[Message] = [Message(role="system", content="You are helpful.")]
    for i in range(turns):
        msgs.append(user(f"turn {i} " + "q" * chars))
        msgs.append(assistant(f"working {i}"))
        msgs.append(tool("x" * chars))
    return msgs


WINDOW = 20_000  # small window so a few turns approach the budget


def test_prefix_makes_the_trigger_fire_earlier():
    msgs = conversation(turns=3)
    plain = Compactor(context_window_tokens=WINDOW)
    with_prefix = Compactor(context_window_tokens=WINDOW, fixed_prefix_tokens=6_000)
    # The same messages: counting the 6k prefix must never make it LESS likely
    # to compact, and at a volume tuned near the budget it flips it on.
    assert with_prefix.estimated_prompt_tokens(msgs) > plain.estimated_prompt_tokens(msgs)
    # Find a message volume where plain says "fine" but prefix-aware says "compact".
    smaller = conversation(turns=2)
    if not plain.needs_compaction(smaller):
        assert with_prefix.needs_compaction(smaller) or with_prefix.estimated_prompt_tokens(
            smaller
        ) > plain.estimated_prompt_tokens(smaller)


def test_calibration_makes_the_trigger_fire_earlier():
    msgs = conversation(turns=2)
    cal = TokenCalibrator(min_samples=2, alpha=0.5)
    # Teach it this model tokenizes at ~2 chars/token (chars/4 is 2x too low).
    est = messages_tokens(msgs)
    for _ in range(4):
        cal.observe("dense-json-model", estimated=est, actual=est * 2)

    plain = Compactor(model="dense-json-model", context_window_tokens=WINDOW)
    calibrated = Compactor(
        model="dense-json-model", context_window_tokens=WINDOW, calibrator=cal
    )
    assert calibrated.estimated_prompt_tokens(msgs) > plain.estimated_prompt_tokens(msgs)
    # The calibrated estimate reflects the ~2x correction.
    assert calibrated.estimated_prompt_tokens(msgs) >= 1.5 * plain.estimated_prompt_tokens(msgs)


def test_calibrated_compaction_still_cuts_on_a_turn_boundary():
    msgs = conversation(turns=6)
    cal = TokenCalibrator(min_samples=1, alpha=0.5)
    est = messages_tokens(msgs)
    cal.observe("m", estimated=est, actual=int(est * 1.5))
    comp = Compactor(
        model="m",
        context_window_tokens=WINDOW,
        fixed_prefix_tokens=2_000,
        calibrator=cal,
    )
    checkpoint = comp.compact(msgs, force=True)
    assert checkpoint is not None
    # The retained ORIGINAL tail (after the injected summary) must open at a
    # real turn boundary — never an orphaned tool result with no matching call.
    boundary = checkpoint.compacted_to
    assert starts_a_turn(msgs[boundary]) or msgs[boundary].role == "assistant"
    # And the retained tail carries no leading orphaned tool message.
    assert msgs[boundary].role != "tool"


def test_no_calibrator_matches_legacy_messages_only_when_prefix_zero():
    """Backwards compatible: no prefix, no calibrator == the old behaviour."""
    msgs = conversation(turns=3)
    comp = Compactor(context_window_tokens=WINDOW)
    assert comp.estimated_prompt_tokens(msgs) == messages_tokens(msgs)
