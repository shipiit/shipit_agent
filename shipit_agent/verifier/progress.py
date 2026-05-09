"""Progress check — after each agent iteration, ask a verifier "did we make
progress?" and inject a corrective hint when the agent stalls.

Tracked state across iterations: a rolling list of recent scores and a count
of consecutive sub-threshold iterations. When the streak hits
``progress_window``, ``maybe_nudge()`` returns a user-message dict that the
caller can append to the conversation as a "you're stalling, try a different
angle" intervention.
"""

from __future__ import annotations

import json
from typing import Any

from shipit_agent.parsers.streaming_json import parse_partial_json

from .models import ProgressCheck, VerifierConfig

_PROGRESS_SYSTEM_PROMPT = (
    "You are a progress evaluator for an AI agent working on a goal. "
    "Given the goal and the most recent agent step, rate progress 0.0-1.0:\n"
    "  1.0 = clear progress (e.g. produced a deliverable, answered a sub-question)\n"
    "  0.5 = some progress (information gathered, useful tool call)\n"
    "  0.0 = no progress (repeating prior calls, going in circles, off-topic)\n\n"
    "Reply with a JSON object EXACTLY in this shape:\n"
    '{"score": 0.0-1.0, "summary": "...", "suggested_action": "..." or null}\n\n'
    "Output ONLY the JSON, no prose."
)


class ProgressVerifier:
    """Per-iteration "did we make progress?" check."""

    def __init__(
        self,
        *,
        llm: Any,
        config: VerifierConfig | None = None,
    ) -> None:
        self.llm = llm
        self.config = config or VerifierConfig()
        self._call_count = 0
        self._scores: list[float] = []
        self._streak_below = 0
        self._nudges_used = 0

    def evaluate(
        self,
        *,
        goal: str,
        last_step_summary: str,
        recent_history: list[dict[str, Any]] | None = None,
    ) -> ProgressCheck:
        """Score the most recent agent step. Returns ``ProgressCheck``.

        Called once per iteration. If progress checking is disabled or the
        per-run cap is hit, returns a neutral 0.5 score without an LLM call.
        """
        if not self.config.progress_enabled:
            return ProgressCheck(score=0.5, summary="progress check disabled")
        if self._call_count >= self.config.max_progress_calls_per_run:
            return ProgressCheck(score=0.5, summary="progress cap reached")

        self._call_count += 1

        try:
            text = _invoke(self.llm, goal, last_step_summary, recent_history)
        except Exception as exc:
            # Fail-open — never block the agent
            return ProgressCheck(score=0.5, summary=f"verifier unavailable: {exc}")

        check = _parse_check(text)
        self._scores.append(check.score)

        if check.score < self.config.progress_threshold:
            self._streak_below += 1
        else:
            self._streak_below = 0
        return check

    def maybe_nudge(self, last_check: ProgressCheck) -> dict[str, str] | None:
        """Return a nudge message dict if the streak crossed the window threshold.

        Resets the streak counter after returning so the same nudge doesn't
        fire on every subsequent iteration. Caller is expected to append the
        returned dict to the conversation messages as a user turn.
        """
        if self._streak_below < self.config.progress_window:
            return None
        # Reset so we don't spam nudges on consecutive iterations
        self._streak_below = 0
        self._nudges_used += 1
        suggestion = last_check.suggested_action or (
            "Take a step back and try a different angle. Summarize what you've "
            "learned so far, identify the actual bottleneck, and pick ONE concrete "
            "next action that doesn't repeat anything you've tried."
        )
        text = (
            f"[progress-check] You haven't made meaningful progress in the last "
            f"{self.config.progress_window} iterations. {suggestion}"
        )
        return {"role": "user", "content": text}

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def streak_below(self) -> int:
        return self._streak_below

    @property
    def scores(self) -> list[float]:
        return list(self._scores)

    @property
    def nudges_used(self) -> int:
        return self._nudges_used


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _invoke(
    llm: Any,
    goal: str,
    last_step: str,
    history: list[dict[str, Any]] | None,
) -> str:
    if not hasattr(llm, "complete"):
        raise TypeError("verifier LLM must have a .complete(messages=...) method")
    parts: list[str] = [f"Goal: {goal}"]
    if history:
        tail = history[-3:]
        ctx = []
        for m in tail:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:300]
            ctx.append(f"  [{role}] {content}")
        parts.append("Recent conversation tail:\n" + "\n".join(ctx))
    parts.append(f"Most recent step: {last_step[:600]}")
    parts.append("Score it.")

    messages = [
        {"role": "system", "content": _PROGRESS_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    result = llm.complete(messages=messages)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("content") or result.get("text") or ""
    text_attr = getattr(result, "content", None) or getattr(result, "text", None)
    return text_attr or ""


def _parse_check(text: str) -> ProgressCheck:
    parsed = parse_partial_json(text) or {}
    if not isinstance(parsed, dict):
        return ProgressCheck(score=0.5, summary="progress response not parseable")
    score = parsed.get("score", 0.5)
    if isinstance(score, (int, float)):
        score = max(0.0, min(1.0, float(score)))
    else:
        try:
            score = max(0.0, min(1.0, float(json.dumps(score))))
        except (TypeError, ValueError):
            score = 0.5
    summary = str(parsed.get("summary", ""))[:200]
    suggested = parsed.get("suggested_action")
    suggested = str(suggested)[:300] if isinstance(suggested, str) else None
    return ProgressCheck(score=score, summary=summary, suggested_action=suggested)
