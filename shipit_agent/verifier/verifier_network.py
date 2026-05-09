"""Combined verifier orchestrator — the public API.

Wraps both pre-tool veto and progress checks behind a single class. Handed
to ``Agent(verifier=...)`` and used internally to wrap tools and inject
progress nudges. Exposes telemetry counters so callers can see how often
the verifier acted.
"""

from __future__ import annotations

from typing import Any

from .models import (
    PreToolDecision,
    ProgressCheck,
    VerifierConfig,
    VerifierStats,
    VerifierVerdict,
)
from .pre_tool import PreToolVerifier, wrap_tool_with_verifier
from .progress import ProgressVerifier


class VerifierNetwork:
    """Combined pre-tool + progress verifier for an agent run.

    Args:
        llm: The LLM to use for verifier checks. Often a cheap/fast model
            (e.g. Haiku) backstopping a more expensive main agent (e.g. Opus).
            Must expose ``.complete(messages=...)``.
        config: Tunables. Defaults are sensible (veto + progress both on).
        goal: Optional human-readable goal string used in pre-tool prompts.

    Example::

        from shipit_agent import Agent
        from shipit_agent.verifier import VerifierNetwork, VerifierConfig

        verifier = VerifierNetwork(
            llm=cheap_llm,
            config=VerifierConfig(veto_enabled=True, progress_enabled=True),
            goal="Build a working authentication API",
        )
        agent = Agent(llm=opus_llm, tools=tools, verifier=verifier)
    """

    def __init__(
        self,
        *,
        llm: Any,
        config: VerifierConfig | None = None,
        goal: str = "",
    ) -> None:
        self.llm = llm
        self.config = config or VerifierConfig()
        self.goal = goal
        self.pre_tool = PreToolVerifier(llm=llm, config=self.config)
        self.progress = ProgressVerifier(llm=llm, config=self.config)
        self._stats = VerifierStats()

    # ------------------------------------------------------------------
    # Pre-tool API
    # ------------------------------------------------------------------
    def check_tool(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        recent_history: list[dict[str, Any]] | None = None,
    ) -> PreToolDecision:
        """Run a pre-tool check and update telemetry."""
        decision = self.pre_tool.check(
            tool_name=tool_name,
            tool_args=tool_args,
            goal=self.goal,
            recent_history=recent_history,
        )
        self._stats.pretool_calls = self.pre_tool.call_count
        if decision.verdict == VerifierVerdict.ALLOW:
            self._stats.pretool_allow += 1
        elif decision.verdict == VerifierVerdict.VETO:
            self._stats.pretool_veto += 1
        else:
            self._stats.pretool_rewrite += 1
        return decision

    def wrap_tools(self, tools: list[Any]) -> list[Any]:
        """Return wrapped versions of the given tools.

        Each wrapped tool calls the verifier's ``check_tool`` before invoking
        the inner tool's ``run()``. Vetoed calls return synthetic error
        outputs so the agent's existing tool-error handling kicks in.

        If veto is disabled in the config, returns the input list unchanged
        — no allocation overhead when the feature is off.
        """
        if not self.config.veto_enabled:
            return list(tools)
        return [wrap_tool_with_verifier(t, self.pre_tool, goal=self.goal) for t in tools]

    # ------------------------------------------------------------------
    # Progress API
    # ------------------------------------------------------------------
    def evaluate_step(
        self,
        *,
        last_step_summary: str,
        recent_history: list[dict[str, Any]] | None = None,
    ) -> ProgressCheck:
        """Score the most recent step and update streak counters."""
        check = self.progress.evaluate(
            goal=self.goal,
            last_step_summary=last_step_summary,
            recent_history=recent_history,
        )
        self._stats.progress_calls = self.progress.call_count
        self._stats.last_progress_scores = self.progress.scores[-10:]
        if check.score < self.config.progress_threshold:
            self._stats.progress_below_threshold += 1
        return check

    def maybe_nudge(self, last_check: ProgressCheck) -> dict[str, str] | None:
        """Return a "you're stalling" nudge if the streak crossed the window."""
        nudge = self.progress.maybe_nudge(last_check)
        if nudge is not None:
            self._stats.nudges_injected = self.progress.nudges_used
        return nudge

    # ------------------------------------------------------------------
    # Telemetry / control
    # ------------------------------------------------------------------
    @property
    def stats(self) -> VerifierStats:
        return self._stats

    def reset(self) -> None:
        """Clear all per-run state. Call between independent agent runs."""
        self.pre_tool = PreToolVerifier(llm=self.llm, config=self.config)
        self.progress = ProgressVerifier(llm=self.llm, config=self.config)
        self._stats = VerifierStats()


__all__ = ["VerifierNetwork"]
