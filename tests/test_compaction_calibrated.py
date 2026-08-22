"""Prefix-aware + calibrated compaction: it fires at the RIGHT time.

Two long-standing under-counts made the trigger fire late — late enough that a
tool-heavy prompt overflows the provider. These tests pin the fixes:
  1. the fixed prefix (system prompt + tool schemas) counts toward the trigger;
  2. a learned per-model calibration factor scales the estimate.
Both must fire *earlier* than the old messages-only estimate, and cuts must
still land on turn/step boundaries so no tool result is orphaned.
"""
from __future__ import annotations

import pytest

from shipit_agent.compaction import (
    Compactor,
    count_messages,
    messages_tokens,
    starts_a_turn,
)
from shipit_agent.models import Message
from shipit_agent.runtime import AgentRuntime
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


def test_no_calibrator_and_no_prefix_is_exactly_the_message_count():
    """With nothing added, the trigger counts the messages and nothing else.

    This used to assert equality with ``messages_tokens`` — the raw
    ``chars/4`` estimator. The counter is now the real per-model tokenizer
    where one is obtainable, so the identity that matters is against
    ``count_messages``: the *same* function the boundary walk and the
    calibrator use. Pinning the old estimator here would have re-introduced
    the unit split those three consumers must not have.
    """
    msgs = conversation(turns=3)
    comp = Compactor(context_window_tokens=WINDOW)
    assert comp.estimated_prompt_tokens(msgs) == count_messages(msgs, comp.model)


def test_real_counting_beats_the_estimate_on_dense_json():
    """The reason for the change: ``chars/4`` under-counts dense tool output,
    which is precisely the shape that most needs compacting."""
    import json

    from shipit_agent.token_counting import real_counting_available

    if not real_counting_available():
        pytest.skip("no tokenizer available in this environment")

    blob = json.dumps({"rows": [{"id": i, "name": "x" * 8} for i in range(60)]})
    msgs = [Message(role="tool", content=blob)]
    assert count_messages(msgs, "gpt-4o") > messages_tokens(msgs)


def test_counting_degrades_to_the_estimate_without_a_tokenizer(monkeypatch):
    """The tokenizer is optional; losing it must cost accuracy, not the run."""
    import shipit_agent.token_counting as tc

    monkeypatch.setattr(tc, "_litellm_count", lambda *_a, **_k: None)
    msgs = conversation(turns=2)
    assert count_messages(msgs, "gpt-4o") == messages_tokens(msgs)


def test_runtime_accounts_for_live_tool_schemas_before_first_completion():
    class LLM:
        model = "gpt-4o"

        def complete(self, **_kwargs):
            return None

    runtime = AgentRuntime(llm=LLM(), prompt="p", fixed_prefix_tokens=123)
    schemas = [{
        "type": "function",
        "function": {
            "name": "search",
            "description": "x" * 4_000,
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    runtime.account_request_overhead(schemas)

    assert runtime._fixed_prefix_tokens > 123
    assert runtime.compactor().fixed_prefix_tokens == runtime._fixed_prefix_tokens
    runtime.account_request_overhead([])
    assert runtime._fixed_prefix_tokens == 123
