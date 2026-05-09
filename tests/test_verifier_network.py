"""Tests for the verifier network — pre-tool veto + progress check.

Each public function gets ≥10 tests covering:
- happy path
- veto / rewrite / nudge logic
- low-confidence downgrade
- per-run caps
- LLM-failure fail-open behaviour (verifier MUST NOT block the agent)
- malformed verifier output handling
- telemetry counters
- Agent integration via constructor arg.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.verifier import (
    PreToolVerifier,
    ProgressCheck,
    ProgressVerifier,
    VerifierConfig,
    VerifierNetwork,
    VerifierVerdict,
    wrap_tool_with_verifier,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class StubLLM:
    """LLM double that returns canned text from a list."""

    responses: list[str] = field(default_factory=list)
    calls: list[list[dict[str, Any]]] = field(default_factory=list)
    _i: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append(list(messages))
        if self._i >= len(self.responses):
            raise RuntimeError(f"StubLLM exhausted at call {self._i}")
        out = self.responses[self._i]
        self._i += 1
        return out


@dataclass
class FailingLLM:
    """LLM that always raises — used to exercise the fail-open path."""

    def complete(self, **_: Any) -> str:
        raise RuntimeError("verifier service unreachable")


class FakeTool:
    """Minimal Tool-protocol stub for wrapping tests."""

    def __init__(self, name: str, return_text: str = "ok") -> None:
        self.name = name
        self.description = f"a {name} tool"
        self.prompt = ""
        self.prompt_instructions = ""
        self._return_text = return_text
        self.run_calls: list[tuple[Any, dict[str, Any]]] = []

    def schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        self.run_calls.append((context, kwargs))
        # Mimic ToolOutput shape — return a duck-type with .text + .metadata
        return _TO(text=self._return_text, metadata={})


class _TO:
    __slots__ = ("text", "metadata")

    def __init__(self, *, text: str, metadata: dict[str, Any]) -> None:
        self.text = text
        self.metadata = metadata


def _allow_response(reason: str = "looks fine", confidence: float = 0.9) -> str:
    return json.dumps({"verdict": "allow", "reason": reason, "confidence": confidence})


def _veto_response(reason: str = "no", confidence: float = 0.9) -> str:
    return json.dumps({"verdict": "veto", "reason": reason, "confidence": confidence})


def _rewrite_response(new_args: dict[str, Any], confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "verdict": "rewrite",
            "reason": "fix arg",
            "confidence": confidence,
            "new_args": new_args,
        }
    )


def _progress_response(score: float, summary: str = "ok", action: str | None = None) -> str:
    return json.dumps({"score": score, "summary": summary, "suggested_action": action})


# ===========================================================================
# PreToolVerifier.check  (≥10 tests)
# ===========================================================================


class TestPreToolVerifierCheck:
    def test_allow_returns_allow_verdict(self) -> None:
        v = PreToolVerifier(llm=StubLLM([_allow_response()]))
        d = v.check(tool_name="read_file", tool_args={"path": "x.py"})
        assert d.verdict == VerifierVerdict.ALLOW

    def test_veto_returns_veto_verdict(self) -> None:
        v = PreToolVerifier(llm=StubLLM([_veto_response("destructive")]))
        d = v.check(tool_name="rm_rf", tool_args={"path": "/"})
        assert d.verdict == VerifierVerdict.VETO
        assert "destructive" in d.reason

    def test_rewrite_includes_new_args(self) -> None:
        v = PreToolVerifier(llm=StubLLM([_rewrite_response({"path": "fixed.py"})]))
        d = v.check(tool_name="read_file", tool_args={"path": "wrong.py"})
        assert d.verdict == VerifierVerdict.REWRITE
        assert d.new_args == {"path": "fixed.py"}

    def test_low_confidence_veto_downgrades_to_allow(self) -> None:
        cfg = VerifierConfig(veto_min_confidence=0.7)
        v = PreToolVerifier(llm=StubLLM([_veto_response(confidence=0.4)]), config=cfg)
        d = v.check(tool_name="t", tool_args={})
        assert d.verdict == VerifierVerdict.ALLOW
        assert "low confidence" in d.reason

    def test_disabled_config_returns_allow_without_llm_call(self) -> None:
        llm = StubLLM([])
        v = PreToolVerifier(llm=llm, config=VerifierConfig(veto_enabled=False))
        d = v.check(tool_name="t", tool_args={})
        assert d.verdict == VerifierVerdict.ALLOW
        assert llm._i == 0  # no LLM invocation

    def test_per_run_cap_short_circuits(self) -> None:
        cfg = VerifierConfig(max_pretool_calls_per_run=1)
        llm = StubLLM([_veto_response()] * 5)
        v = PreToolVerifier(llm=llm, config=cfg)
        first = v.check(tool_name="t", tool_args={})
        second = v.check(tool_name="t", tool_args={})
        assert first.verdict == VerifierVerdict.VETO
        assert second.verdict == VerifierVerdict.ALLOW
        assert "cap reached" in second.reason

    def test_failing_llm_fails_open(self) -> None:
        v = PreToolVerifier(llm=FailingLLM())
        d = v.check(tool_name="t", tool_args={})
        # Verifier MUST NOT block on its own failure
        assert d.verdict == VerifierVerdict.ALLOW
        assert "unavailable" in d.reason

    def test_malformed_response_fails_open(self) -> None:
        v = PreToolVerifier(llm=StubLLM(["this is not json at all"]))
        d = v.check(tool_name="t", tool_args={})
        assert d.verdict == VerifierVerdict.ALLOW

    def test_call_count_increments(self) -> None:
        v = PreToolVerifier(llm=StubLLM([_allow_response(), _allow_response()]))
        v.check(tool_name="t", tool_args={})
        v.check(tool_name="t", tool_args={})
        assert v.call_count == 2

    def test_recent_history_passed_to_llm(self) -> None:
        llm = StubLLM([_allow_response()])
        v = PreToolVerifier(llm=llm)
        history = [{"role": "user", "content": "hello world"}]
        v.check(tool_name="t", tool_args={}, recent_history=history)
        user_msg = llm.calls[0][-1]["content"]
        assert "hello world" in user_msg

    def test_goal_passed_to_llm(self) -> None:
        llm = StubLLM([_allow_response()])
        v = PreToolVerifier(llm=llm)
        v.check(tool_name="t", tool_args={}, goal="climb mount everest")
        assert "climb mount everest" in llm.calls[0][-1]["content"]

    def test_textual_verdict_synonyms_parse_correctly(self) -> None:
        v = PreToolVerifier(llm=StubLLM([json.dumps({"verdict": "block this", "confidence": 0.9})]))
        d = v.check(tool_name="t", tool_args={})
        assert d.verdict == VerifierVerdict.VETO


# ===========================================================================
# wrap_tool_with_verifier  (≥10 tests)
# ===========================================================================


class TestWrapToolWithVerifier:
    def _make(self, response: str) -> tuple[FakeTool, Any, PreToolVerifier]:
        v = PreToolVerifier(llm=StubLLM([response]))
        tool = FakeTool("read_file")
        wrapped = wrap_tool_with_verifier(tool, v)
        return tool, wrapped, v

    def test_wrapped_tool_preserves_name(self) -> None:
        _, wrapped, _ = self._make(_allow_response())
        assert wrapped.name == "read_file"

    def test_wrapped_tool_preserves_description(self) -> None:
        _, wrapped, _ = self._make(_allow_response())
        assert "read_file" in wrapped.description

    def test_wrapped_tool_preserves_schema(self) -> None:
        _, wrapped, _ = self._make(_allow_response())
        assert wrapped.schema() == {"type": "object", "properties": {}}

    def test_allow_runs_inner_tool(self) -> None:
        inner, wrapped, _ = self._make(_allow_response())
        result = wrapped.run(path="x.py")
        assert len(inner.run_calls) == 1
        assert inner.run_calls[0][1] == {"path": "x.py"}
        assert result.text == "ok"

    def test_veto_blocks_inner_tool(self) -> None:
        inner, wrapped, _ = self._make(_veto_response("nope"))
        result = wrapped.run(path="x.py")
        assert inner.run_calls == []  # inner never invoked
        assert "verifier-veto" in result.text
        assert result.metadata.get("verifier_veto") is True

    def test_rewrite_passes_new_args_to_inner(self) -> None:
        inner, wrapped, _ = self._make(
            _rewrite_response(new_args={"path": "corrected.py"})
        )
        wrapped.run(path="bad.py")
        assert inner.run_calls[0][1] == {"path": "corrected.py"}

    def test_rewrite_without_new_args_passes_original(self) -> None:
        # If verdict says rewrite but new_args is missing, fall back to original args.
        v = PreToolVerifier(
            llm=StubLLM([json.dumps({"verdict": "rewrite", "confidence": 0.9})])
        )
        inner = FakeTool("t")
        wrapped = wrap_tool_with_verifier(inner, v)
        wrapped.run(path="x")
        assert inner.run_calls[0][1] == {"path": "x"}

    def test_context_arg_forwarded(self) -> None:
        inner, wrapped, _ = self._make(_allow_response())
        ctx = object()
        wrapped.run(ctx, path="x.py")
        assert inner.run_calls[0][0] is ctx

    def test_no_context_arg_when_omitted(self) -> None:
        inner, wrapped, _ = self._make(_allow_response())
        wrapped.run(path="x.py")
        assert inner.run_calls[0][0] is None

    def test_failing_verifier_passes_through(self) -> None:
        v = PreToolVerifier(llm=FailingLLM())
        inner = FakeTool("t")
        wrapped = wrap_tool_with_verifier(inner, v)
        wrapped.run(path="x")
        # Fail-open means inner runs
        assert len(inner.run_calls) == 1

    def test_multiple_calls_use_separate_responses(self) -> None:
        v = PreToolVerifier(llm=StubLLM([_allow_response(), _veto_response()]))
        inner = FakeTool("t")
        wrapped = wrap_tool_with_verifier(inner, v)
        first = wrapped.run(path="x")
        second = wrapped.run(path="y")
        assert first.text == "ok"
        assert "verifier-veto" in second.text
        assert len(inner.run_calls) == 1  # only first allowed


# ===========================================================================
# ProgressVerifier.evaluate + maybe_nudge  (≥10 tests)
# ===========================================================================


class TestProgressVerifierEvaluate:
    def test_high_score_returns_progresscheck(self) -> None:
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.9, "good")]))
        c = v.evaluate(goal="g", last_step_summary="step")
        assert c.score == 0.9

    def test_low_score_increments_streak(self) -> None:
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.1)] * 3))
        for _ in range(3):
            v.evaluate(goal="g", last_step_summary="step")
        assert v.streak_below == 3

    def test_high_score_resets_streak(self) -> None:
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1), _progress_response(0.9)])
        )
        v.evaluate(goal="g", last_step_summary="s")
        v.evaluate(goal="g", last_step_summary="s")
        assert v.streak_below == 0

    def test_disabled_returns_neutral(self) -> None:
        v = ProgressVerifier(
            llm=StubLLM([]), config=VerifierConfig(progress_enabled=False)
        )
        c = v.evaluate(goal="g", last_step_summary="s")
        assert c.score == 0.5

    def test_per_run_cap_short_circuits(self) -> None:
        cfg = VerifierConfig(max_progress_calls_per_run=1)
        llm = StubLLM([_progress_response(0.1)] * 3)
        v = ProgressVerifier(llm=llm, config=cfg)
        first = v.evaluate(goal="g", last_step_summary="s")
        second = v.evaluate(goal="g", last_step_summary="s")
        assert first.score == 0.1
        assert second.score == 0.5  # cap kicks in

    def test_failing_llm_returns_neutral(self) -> None:
        v = ProgressVerifier(llm=FailingLLM())
        c = v.evaluate(goal="g", last_step_summary="s")
        assert c.score == 0.5

    def test_malformed_response_returns_neutral(self) -> None:
        v = ProgressVerifier(llm=StubLLM(["totally not json"]))
        c = v.evaluate(goal="g", last_step_summary="s")
        assert c.score == 0.5

    def test_score_clamped_to_unit_interval(self) -> None:
        v = ProgressVerifier(llm=StubLLM([_progress_response(2.5)]))
        c = v.evaluate(goal="g", last_step_summary="s")
        assert 0.0 <= c.score <= 1.0

    def test_negative_score_clamped(self) -> None:
        v = ProgressVerifier(llm=StubLLM([_progress_response(-0.5)]))
        c = v.evaluate(goal="g", last_step_summary="s")
        assert c.score == 0.0

    def test_scores_history_tracked(self) -> None:
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(s) for s in [0.1, 0.5, 0.9]])
        )
        for _ in range(3):
            v.evaluate(goal="g", last_step_summary="s")
        assert v.scores == [0.1, 0.5, 0.9]

    def test_call_count_increments(self) -> None:
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.5)] * 3))
        for _ in range(3):
            v.evaluate(goal="g", last_step_summary="s")
        assert v.call_count == 3


class TestProgressVerifierMaybeNudge:
    def test_no_nudge_when_streak_below_window(self) -> None:
        cfg = VerifierConfig(progress_window=3)
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1), _progress_response(0.1)]),
            config=cfg,
        )
        for _ in range(2):
            v.evaluate(goal="g", last_step_summary="s")
        assert v.maybe_nudge(ProgressCheck(score=0.1)) is None

    def test_nudge_when_streak_hits_window(self) -> None:
        cfg = VerifierConfig(progress_window=3)
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1)] * 3), config=cfg
        )
        last = None
        for _ in range(3):
            last = v.evaluate(goal="g", last_step_summary="s")
        nudge = v.maybe_nudge(last)
        assert nudge is not None
        assert nudge["role"] == "user"
        assert "progress-check" in nudge["content"]

    def test_nudge_resets_streak(self) -> None:
        cfg = VerifierConfig(progress_window=2)
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1)] * 2), config=cfg
        )
        last = None
        for _ in range(2):
            last = v.evaluate(goal="g", last_step_summary="s")
        v.maybe_nudge(last)
        assert v.streak_below == 0

    def test_nudge_uses_suggested_action_when_present(self) -> None:
        cfg = VerifierConfig(progress_window=1)
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1, action="try X")]),
            config=cfg,
        )
        last = v.evaluate(goal="g", last_step_summary="s")
        nudge = v.maybe_nudge(last)
        assert nudge is not None
        assert "try X" in nudge["content"]

    def test_nudge_uses_default_when_no_suggestion(self) -> None:
        cfg = VerifierConfig(progress_window=1)
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.1)]), config=cfg)
        last = v.evaluate(goal="g", last_step_summary="s")
        nudge = v.maybe_nudge(last)
        assert nudge is not None
        assert "different angle" in nudge["content"]

    def test_nudge_count_increments(self) -> None:
        cfg = VerifierConfig(progress_window=1)
        v = ProgressVerifier(
            llm=StubLLM([_progress_response(0.1)] * 4), config=cfg
        )
        for _ in range(4):
            last = v.evaluate(goal="g", last_step_summary="s")
            v.maybe_nudge(last)
        assert v.nudges_used == 4

    def test_high_score_no_nudge(self) -> None:
        cfg = VerifierConfig(progress_window=2)
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.9)]), config=cfg)
        last = v.evaluate(goal="g", last_step_summary="s")
        assert v.maybe_nudge(last) is None

    def test_window_one_immediate_nudge(self) -> None:
        cfg = VerifierConfig(progress_window=1)
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.1)]), config=cfg)
        last = v.evaluate(goal="g", last_step_summary="s")
        assert v.maybe_nudge(last) is not None

    def test_disabled_progress_no_nudge(self) -> None:
        cfg = VerifierConfig(progress_enabled=False)
        v = ProgressVerifier(llm=StubLLM([]), config=cfg)
        last = v.evaluate(goal="g", last_step_summary="s")
        assert v.maybe_nudge(last) is None

    def test_threshold_boundary_score_does_not_count(self) -> None:
        cfg = VerifierConfig(progress_threshold=0.4, progress_window=1)
        # Score == threshold is NOT below
        v = ProgressVerifier(llm=StubLLM([_progress_response(0.4)]), config=cfg)
        last = v.evaluate(goal="g", last_step_summary="s")
        assert v.maybe_nudge(last) is None


# ===========================================================================
# VerifierNetwork (orchestrator) (≥10 tests)
# ===========================================================================


class TestVerifierNetwork:
    def test_check_tool_records_allow(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_allow_response()]))
        n.check_tool(tool_name="t", tool_args={})
        assert n.stats.pretool_allow == 1

    def test_check_tool_records_veto(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_veto_response()]))
        n.check_tool(tool_name="t", tool_args={})
        assert n.stats.pretool_veto == 1

    def test_check_tool_records_rewrite(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_rewrite_response({"x": 1})]))
        n.check_tool(tool_name="t", tool_args={})
        assert n.stats.pretool_rewrite == 1

    def test_wrap_tools_returns_wrappers(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_allow_response()]))
        tools = [FakeTool("a"), FakeTool("b")]
        wrapped = n.wrap_tools(tools)
        assert len(wrapped) == 2
        assert wrapped[0].name == "a"
        assert wrapped[0] is not tools[0]  # actually wrapped

    def test_wrap_tools_passthrough_when_disabled(self) -> None:
        cfg = VerifierConfig(veto_enabled=False)
        n = VerifierNetwork(llm=StubLLM([]), config=cfg)
        tools = [FakeTool("a")]
        wrapped = n.wrap_tools(tools)
        # When veto disabled, return unwrapped (avoid wrapping cost)
        assert wrapped[0] is tools[0]

    def test_evaluate_step_updates_stats(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_progress_response(0.2)]))
        n.evaluate_step(last_step_summary="step")
        assert n.stats.progress_calls == 1
        assert n.stats.progress_below_threshold == 1

    def test_evaluate_step_high_score_no_threshold_count(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_progress_response(0.9)]))
        n.evaluate_step(last_step_summary="step")
        assert n.stats.progress_below_threshold == 0

    def test_maybe_nudge_records_telemetry(self) -> None:
        cfg = VerifierConfig(progress_window=1)
        n = VerifierNetwork(llm=StubLLM([_progress_response(0.1)]), config=cfg)
        last = n.evaluate_step(last_step_summary="step")
        nudge = n.maybe_nudge(last)
        assert nudge is not None
        assert n.stats.nudges_injected == 1

    def test_reset_clears_state(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_allow_response(), _allow_response()]))
        n.check_tool(tool_name="t", tool_args={})
        n.reset()
        assert n.stats.pretool_calls == 0
        assert n.stats.pretool_allow == 0
        # New verifier instances after reset, fresh internal counters
        assert n.pre_tool.call_count == 0

    def test_goal_propagated_to_pretool(self) -> None:
        llm = StubLLM([_allow_response()])
        n = VerifierNetwork(llm=llm, goal="ship v1.0.8")
        tools = n.wrap_tools([FakeTool("t")])
        tools[0].run(path="x")
        # Look at the LLM call that the verifier made — first call
        verifier_msg = llm.calls[0][-1]["content"]
        assert "ship v1.0.8" in verifier_msg

    def test_progress_scores_appear_in_stats(self) -> None:
        n = VerifierNetwork(
            llm=StubLLM([_progress_response(s) for s in [0.2, 0.5, 0.8]])
        )
        for _ in range(3):
            n.evaluate_step(last_step_summary="s")
        assert n.stats.last_progress_scores == [0.2, 0.5, 0.8]

    def test_pretool_total_calls_aggregates(self) -> None:
        n = VerifierNetwork(llm=StubLLM([_allow_response()] * 4))
        for _ in range(4):
            n.check_tool(tool_name="t", tool_args={})
        assert n.stats.pretool_calls == 4
        assert n.stats.pretool_allow == 4


# ===========================================================================
# Agent integration  (≥10 tests)
# ===========================================================================


class TestAgentVerifierIntegration:
    """End-to-end: ``Agent(verifier=...)`` actually wraps tools."""

    def test_agent_accepts_verifier_kwarg(self) -> None:
        from shipit_agent import Agent

        # Smoke test — constructor doesn't reject the new kwarg
        agent = Agent(llm=StubLLM([]), verifier=None)
        assert agent.verifier is None

    def test_agent_with_verifier_wraps_tools(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_allow_response()] * 5))
        tool = FakeTool("t")
        agent = Agent(
            llm=StubLLM([]),
            tools=[tool],
            verifier=n,
            auto_use_skills=False,
        )
        effective = agent._effective_tools("any prompt")  # noqa: SLF001
        # Tools list should contain a wrapper, not the raw tool
        assert effective[0] is not tool
        assert effective[0].name == "t"

    def test_agent_without_verifier_does_not_wrap(self) -> None:
        from shipit_agent import Agent

        tool = FakeTool("t")
        agent = Agent(llm=StubLLM([]), tools=[tool], auto_use_skills=False)
        effective = agent._effective_tools("any prompt")  # noqa: SLF001
        assert effective[0] is tool

    def test_agent_with_disabled_verifier_does_not_wrap(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(
            llm=StubLLM([]), config=VerifierConfig(veto_enabled=False)
        )
        tool = FakeTool("t")
        agent = Agent(
            llm=StubLLM([]), tools=[tool], verifier=n, auto_use_skills=False
        )
        effective = agent._effective_tools("any prompt")  # noqa: SLF001
        # veto disabled → wrap_tools returns input unchanged
        assert effective[0] is tool

    def test_agent_verifier_telemetry_accessible(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_allow_response()]))
        agent = Agent(llm=StubLLM([]), verifier=n)
        # Caller can read agent.verifier.stats post-run
        assert agent.verifier.stats.pretool_calls == 0

    def test_two_agents_share_verifier_separately(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_allow_response()] * 10))
        a1 = Agent(llm=StubLLM([]), verifier=n)
        a2 = Agent(llm=StubLLM([]), verifier=n)
        # Stats are shared by reference; users should call .reset() between runs
        assert a1.verifier is a2.verifier

    def test_agent_handles_non_verifier_object_gracefully(self) -> None:
        from shipit_agent import Agent

        # A garbage value passed as `verifier=` shouldn't crash _effective_tools.
        # The hasattr check makes the integration safe.
        agent = Agent(llm=StubLLM([]), tools=[FakeTool("t")], verifier=object())
        effective = agent._effective_tools("any")  # noqa: SLF001
        assert effective[0].name == "t"

    def test_agent_verifier_works_with_multiple_tools(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_allow_response()] * 10))
        tools = [FakeTool("a"), FakeTool("b"), FakeTool("c")]
        agent = Agent(llm=StubLLM([]), tools=tools, verifier=n, auto_use_skills=False)
        effective = agent._effective_tools("any")  # noqa: SLF001
        assert {t.name for t in effective} == {"a", "b", "c"}

    def test_agent_verifier_preserves_tool_run_when_allow(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_allow_response()]))
        tool = FakeTool("t", return_text="real-result")
        agent = Agent(llm=StubLLM([]), tools=[tool], verifier=n, auto_use_skills=False)
        effective = agent._effective_tools("any")  # noqa: SLF001
        result = effective[0].run(path="x")
        assert result.text == "real-result"

    def test_agent_verifier_blocks_tool_when_veto(self) -> None:
        from shipit_agent import Agent

        n = VerifierNetwork(llm=StubLLM([_veto_response("dangerous")]))
        tool = FakeTool("rm_rf", return_text="should not run")
        agent = Agent(llm=StubLLM([]), tools=[tool], verifier=n, auto_use_skills=False)
        effective = agent._effective_tools("any")  # noqa: SLF001
        result = effective[0].run(path="/")
        assert "verifier-veto" in result.text
        assert tool.run_calls == []  # never called


# Marker used implicitly by pytest collectors but referenced for grep clarity
_ = pytest
