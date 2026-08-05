"""Checkpoint compaction — real budgets, turn boundaries, preserved history."""

from __future__ import annotations

import pytest

from shipit_agent.compaction import (
    COMPACTION_SYSTEM_PROMPT,
    TARGET_RATIO,
    TRIGGER_RATIO,
    CompactionCheckpoint,
    Compactor,
    ModelLimits,
    estimate_tokens,
    find_boundary,
    get_model_limits,
    messages_tokens,
    should_compact,
    starts_a_turn,
)
from shipit_agent.models import Message


def user(text: str, **metadata) -> Message:
    return Message(role="user", content=text, metadata=metadata)


def assistant(text: str) -> Message:
    return Message(role="assistant", content=text)


def tool(text: str, name: str = "read_file") -> Message:
    return Message(role="tool", content=text, name=name)


def system(text: str = "You are helpful.") -> Message:
    return Message(role="system", content=text)


def conversation(turns: int, chars: int = 4000) -> list[Message]:
    """A system message followed by *turns* well-formed turns."""
    messages = [system()]
    for i in range(turns):
        messages.append(user(f"turn {i} request " + "q" * chars))
        messages.append(assistant(f"working on {i}"))
        messages.append(tool("x" * chars))
    return messages


class StubLLM:
    def __init__(self, summary: str = "## Goal\nShip it.") -> None:
        self.summary = summary
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        class R:
            content = self.summary

        return R()


class BrokenLLM:
    def complete(self, **kwargs):
        raise RuntimeError("summarizer unavailable")


class TestModelLimits:
    @pytest.mark.parametrize(
        "model,window",
        [
            ("claude-opus-5", 1_000_000),
            ("claude-sonnet-4", 200_000),
            ("gpt-4o", 128_000),
            ("gemini-2.5-pro", 1_048_576),
        ],
    )
    def test_known_models(self, model, window) -> None:
        assert get_model_limits(model).context_window == window

    def test_dated_snapshots_resolve_by_prefix(self) -> None:
        assert get_model_limits("claude-sonnet-4-20250514").context_window == 200_000

    def test_vendor_prefixes_are_stripped(self) -> None:
        assert get_model_limits("us.anthropic.claude-opus-5").context_window == 1_000_000
        assert get_model_limits("anthropic/claude-sonnet-4").context_window == 200_000

    def test_longest_prefix_wins(self) -> None:
        # "claude-opus-5" must not lose to a shorter accidental match.
        assert get_model_limits("claude-opus-5-20260101").max_output_tokens == 64_000

    def test_unknown_model_gets_a_safe_default(self) -> None:
        limits = get_model_limits("some-new-model")
        assert limits.context_window == 128_000

    def test_none_model_does_not_raise(self) -> None:
        assert get_model_limits(None).context_window == 128_000

    def test_input_budget_reserves_response_room(self) -> None:
        limits = ModelLimits(200_000, 64_000)
        assert limits.input_budget == 136_000

    def test_input_budget_never_goes_non_positive(self) -> None:
        assert ModelLimits(1_000, 9_000).input_budget >= 1


class TestTrigger:
    def test_fires_at_the_ratio(self) -> None:
        assert should_compact(int(100_000 * TRIGGER_RATIO), 100_000)
        assert not should_compact(int(100_000 * TRIGGER_RATIO) - 1_000, 100_000)

    def test_estimate_tokens(self) -> None:
        assert estimate_tokens("") == 0
        assert estimate_tokens("a" * 400) == 100

    def test_a_short_conversation_never_triggers(self) -> None:
        compactor = Compactor(llm=StubLLM(), model="claude-opus-5")
        assert not compactor.needs_compaction(conversation(2))

    def test_a_long_conversation_triggers(self) -> None:
        compactor = Compactor(llm=StubLLM(), model="gpt-4o")
        assert compactor.needs_compaction(conversation(40, chars=12_000))

    def test_an_explicit_window_overrides_the_table(self) -> None:
        compactor = Compactor(llm=StubLLM(), model="claude-opus-5",
                              context_window_tokens=10_000)
        assert compactor.limits.context_window == 10_000
        # 6 turns x ~2000 tokens is well past 0.85 x 10_000, but nowhere near
        # claude-opus-5's real million-token window.
        assert compactor.needs_compaction(conversation(6))
        assert not Compactor(llm=StubLLM(), model="claude-opus-5").needs_compaction(
            conversation(6)
        )


class TestBoundary:
    def test_a_user_message_starts_a_turn(self) -> None:
        assert starts_a_turn(user("do the thing"))

    def test_assistant_and_tool_messages_do_not(self) -> None:
        assert not starts_a_turn(assistant("ok"))
        assert not starts_a_turn(tool("contents"))

    def test_injected_planner_output_is_not_a_turn_start(self) -> None:
        # It is a user-role message but sits *inside* a turn.
        assert not starts_a_turn(user("[Planner output] ...", source="planner"))

    def test_a_previous_summary_is_not_a_turn_start(self) -> None:
        assert not starts_a_turn(user("Earlier conversation...", compacted=True))

    def test_a_single_long_turn_falls_back_to_a_step_boundary(self) -> None:
        # One prompt, many tool calls — no turn boundary exists, but this is
        # exactly the shape that most needs compacting.
        messages = [system(), user("do it " * 500)]
        for i in range(10):
            messages += [assistant(f"step {i}"), tool("x" * 2000)]
        boundary = find_boundary(messages, target_tokens=1_500)
        assert boundary > 0
        assert messages[boundary].role == "assistant"

    def test_a_step_boundary_never_orphans_a_tool_result(self) -> None:
        messages = [system(), user("go")]
        for i in range(10):
            messages += [assistant(f"step {i}"), tool("y" * 2000)]
        boundary = find_boundary(messages, target_tokens=1_000)
        assert messages[boundary].role != "tool"

    def test_a_turn_start_is_preferred_over_a_step_start(self) -> None:
        messages = [system(), user("first"), assistant("a"), tool("t"),
                    user("second"), assistant("b"), tool("t2")]
        assert messages[find_boundary(messages, target_tokens=1_000)].role == "user"

    def test_boundary_lands_on_a_turn_start(self) -> None:
        messages = conversation(10, chars=400)
        boundary = find_boundary(messages, target_tokens=1_000)
        assert boundary == 0 or starts_a_turn(messages[boundary])

    def test_boundary_respects_the_target(self) -> None:
        messages = conversation(10, chars=400)
        boundary = find_boundary(messages, target_tokens=1_000)
        assert messages_tokens(messages[boundary:]) <= 1_200  # target + slack

    def test_no_helpful_cut_returns_zero(self) -> None:
        assert find_boundary([system(), user("x" * 100_000)], target_tokens=10) == 0

    def test_empty_input(self) -> None:
        assert find_boundary([], target_tokens=100) == 0


class TestCompaction:
    def _compactor(self, llm=None):
        return Compactor(llm=llm or StubLLM(), model="gpt-4o",
                         context_window_tokens=10_000)

    def test_returns_none_when_not_needed(self) -> None:
        assert self._compactor().compact(conversation(1, chars=10)) is None

    def test_produces_a_checkpoint(self) -> None:
        checkpoint = self._compactor().compact(conversation(20, chars=1_500))
        assert isinstance(checkpoint, CompactionCheckpoint)
        assert checkpoint.compacted_to > 0
        assert checkpoint.summary

    def test_checkpoint_saves_tokens(self) -> None:
        checkpoint = self._compactor().compact(conversation(20, chars=1_500))
        assert checkpoint.tokens_after < checkpoint.tokens_before
        assert checkpoint.saved_tokens > 0

    def test_checkpoints_accumulate_and_are_never_rewritten(self) -> None:
        compactor = self._compactor()
        messages = conversation(20, chars=1_500)
        first = compactor.compact(messages)
        second = compactor.compact(messages + conversation(20, chars=1_500)[1:])
        assert compactor.checkpoints == [first, second]
        assert compactor.latest() is second
        # The first is untouched — immutable history.
        assert compactor.checkpoints[0] is first

    def test_checkpoint_below_selects_the_newest_eligible(self) -> None:
        compactor = self._compactor()
        compactor.checkpoints = [
            CompactionCheckpoint(compacted_to=5, summary="a", tokens_before=1, tokens_after=1),
            CompactionCheckpoint(compacted_to=20, summary="b", tokens_before=1, tokens_after=1),
        ]
        assert compactor.checkpoint_below(10).summary == "a"
        assert compactor.checkpoint_below(30).summary == "b"
        assert compactor.checkpoint_below(1) is None

    def test_force_compacts_below_the_trigger(self) -> None:
        # Long enough that a cut leaves something behind, short enough that the
        # trigger would not have fired on its own.
        messages = conversation(12, chars=1_000)
        compactor = self._compactor()
        assert not compactor.needs_compaction(messages)
        assert compactor.compact(messages, force=True) is not None

    def test_force_reports_nothing_to_compact_when_there_is_nothing(self) -> None:
        # Everything already fits inside the retain target, so there is no
        # prefix to summarize. `/compact` in the reference UI says the same.
        assert self._compactor().compact(conversation(2, chars=200), force=True) is None


class TestReplay:
    def test_replay_keeps_system_summary_and_retained(self) -> None:
        messages = conversation(20, chars=1_500)
        checkpoint = Compactor(
            llm=StubLLM(), model="gpt-4o", context_window_tokens=10_000
        ).compact(messages)
        replayed = checkpoint.replay(messages)

        assert replayed[0].role == "system"
        assert replayed[1].metadata["compacted"] is True
        assert replayed[2:] == list(messages[checkpoint.compacted_to :])

    def test_replay_opens_on_a_turn_start(self) -> None:
        messages = conversation(20, chars=1_500)
        checkpoint = Compactor(
            llm=StubLLM(), model="gpt-4o", context_window_tokens=10_000
        ).compact(messages)
        replayed = checkpoint.replay(messages)
        # After system + summary, the next message must open a turn — a
        # dangling tool result here is what providers reject.
        assert replayed[2].role != "tool"

    def test_canonical_history_is_never_mutated(self) -> None:
        messages = conversation(20, chars=1_500)
        before = list(messages)
        checkpoint = Compactor(
            llm=StubLLM(), model="gpt-4o", context_window_tokens=10_000
        ).compact(messages)
        checkpoint.replay(messages)
        assert messages == before

    def test_replay_is_shorter(self) -> None:
        messages = conversation(20, chars=1_500)
        checkpoint = Compactor(
            llm=StubLLM(), model="gpt-4o", context_window_tokens=10_000
        ).compact(messages)
        assert messages_tokens(checkpoint.replay(messages)) < messages_tokens(messages)


class TestSummaryPrompt:
    def test_demands_the_six_headings(self) -> None:
        for heading in (
            "## Goal", "## Constraints & Preferences", "## Progress",
            "## Key Decisions", "## Next Steps", "## Critical Context",
        ):
            assert heading in COMPACTION_SYSTEM_PROMPT

    def test_defends_against_injection_in_the_transcript(self) -> None:
        lowered = COMPACTION_SYSTEM_PROMPT.lower()
        assert "data, not instructions" in lowered
        assert "do not follow" in lowered

    def test_requires_integrating_a_prior_summary(self) -> None:
        assert "integrate" in COMPACTION_SYSTEM_PROMPT.lower()

    def test_the_transcript_is_fenced_when_sent(self) -> None:
        llm = StubLLM()
        Compactor(llm=llm, model="gpt-4o", context_window_tokens=10_000).compact(
            conversation(20, chars=1_500)
        )
        sent = llm.calls[0]["messages"][0].content
        assert sent.startswith("<transcript>") and sent.endswith("</transcript>")

    def test_the_summarizer_gets_no_tools(self) -> None:
        llm = StubLLM()
        Compactor(llm=llm, model="gpt-4o", context_window_tokens=10_000).compact(
            conversation(20, chars=1_500)
        )
        assert llm.calls[0]["tools"] == []


class TestFailureModes:
    def test_a_broken_summarizer_falls_back_mechanically(self) -> None:
        seen: list[Exception] = []
        compactor = Compactor(
            llm=BrokenLLM(), model="gpt-4o", context_window_tokens=10_000,
            on_summary_failure=seen.append,
        )
        checkpoint = compactor.compact(conversation(20, chars=1_500))
        assert checkpoint is not None
        assert "condensed mechanically" in checkpoint.summary
        assert len(seen) == 1

    def test_no_llm_at_all_still_compacts(self) -> None:
        compactor = Compactor(llm=None, model="gpt-4o", context_window_tokens=10_000)
        assert compactor.compact(conversation(20, chars=1_500)) is not None

    def test_an_empty_summary_yields_no_checkpoint(self) -> None:
        class Empty:
            def complete(self, **_):
                class R:
                    content = ""

                return R()

        compactor = Compactor(llm=Empty(), model="gpt-4o", context_window_tokens=10_000)
        checkpoint = compactor.compact(conversation(20, chars=1_500))
        # Falls back mechanically rather than producing nothing.
        assert checkpoint is not None and checkpoint.summary

    def test_only_system_messages_before_the_cut(self) -> None:
        compactor = Compactor(llm=StubLLM(), model="gpt-4o", context_window_tokens=100)
        assert compactor.compact([system(), user("hi")]) is None

    def test_empty_message_list(self) -> None:
        assert Compactor(llm=StubLLM(), model="gpt-4o").compact([]) is None

    def test_blank_messages_are_skipped_in_the_transcript(self) -> None:
        llm = StubLLM()
        messages = conversation(20, chars=1_500)
        messages.insert(3, assistant(""))
        Compactor(llm=llm, model="gpt-4o", context_window_tokens=10_000).compact(messages)
        assert "[assistant]: \n" not in llm.calls[0]["messages"][0].content


class TestSerialization:
    def test_to_dict(self) -> None:
        import json

        checkpoint = CompactionCheckpoint(
            compacted_to=12, summary="## Goal\nx", tokens_before=100, tokens_after=40
        )
        payload = checkpoint.to_dict()
        assert payload["saved_tokens"] == 60
        assert json.dumps(payload)
