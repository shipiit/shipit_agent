"""Critic — a per-iteration reflection loop that scores output against criteria.

Wired into Autopilot as an optional hook: after each inner-agent iteration
the critic reviews the output, produces a verdict, and Autopilot feeds the
verdict's suggestions into the next iteration's prompt. Net effect on hard
goals: criteria-met rate goes up, wasted iterations go down.

Two modes:

- ``Critic()``                — default critic using the same LLM the
  caller passed to Autopilot. Cheap and works well for self-check.
- ``Critic(llm=reviewer_llm)``— a dedicated reviewer model. Stronger
  but doubles the per-iteration cost. Recommended only for high-stakes
  goals (security review, compliance, production changes).

The verdict is a plain dict so callers can log it without thinking about
types. Autopilot never acts on low-confidence verdicts — criterion flips
require ``confidence >= confidence_threshold`` (default 0.75).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CriticVerdict:
    """Output of one critic pass over an iteration's result."""

    criteria_met: list[bool] = field(default_factory=list)
    confidence: float = 0.0  # 0..1
    suggestions: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT_CRITIC_PROMPT = """You are a rigorous reviewer. Given an objective, a list of success criteria,
and the agent's most recent output, decide which criteria are actually
satisfied by *evidence in the output* — not by the agent's confidence,
not by what it claims it will do, only what it concretely demonstrates.

Be strict. If a criterion says "has tests" and the output mentions tests
but doesn't show them, criterion is NOT met. If it says "has code snippets"
and the snippets aren't actually present, NOT met.

Respond with ONLY valid JSON in this exact shape:

{
  "criteria_met": [true, false, ...],   // one bool per criterion, in order
  "confidence": 0.0-1.0,                 // your own confidence in this assessment
  "suggestions": ["...", "..."],        // concrete next actions for unmet criteria
  "reasoning": "one short paragraph"    // why you scored what you did
}

Give one entry in `criteria_met` for each criterion in the input list,
in the same order. Do not invent extra criteria.
"""


class Critic:
    """Score iteration output against success criteria.

    The contract is deliberately LLM-agnostic: we construct a prompt,
    call ``llm.complete(messages=[...])`` (the method every shipit_agent
    LLM adapter implements), and parse the JSON reply. If parsing fails
    we return a zero-confidence verdict rather than raising — Autopilot
    then simply won't short-circuit on criteria satisfaction that pass.
    """

    def __init__(
        self,
        *,
        llm: Any | None = None,
        system_prompt: str | None = None,
        confidence_threshold: float = 0.75,
        max_suggestions: int = 5,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt or _DEFAULT_CRITIC_PROMPT
        self.confidence_threshold = confidence_threshold
        self.max_suggestions = max_suggestions

    # ── public API ───────────────────────────────────────────────

    def review(
        self,
        *,
        objective: str,
        criteria: list[str],
        output: str,
        fallback_llm: Any | None = None,
    ) -> CriticVerdict:
        """Run one critic pass; returns a :class:`CriticVerdict`.

        ``fallback_llm`` is used when this critic was constructed without
        one — Autopilot passes its own LLM so the default critic is free
        for the caller.
        """
        llm = self.llm or fallback_llm
        if llm is None:
            return CriticVerdict()

        prompt = self._build_prompt(
            objective=objective, criteria=criteria, output=output
        )
        try:
            raw = self._complete(llm, prompt)
        except Exception:  # noqa: BLE001 — never let a critic error kill a run
            return CriticVerdict(reasoning="critic raised; skipped.")

        verdict = self._parse(raw, n_criteria=len(criteria))
        # Cap suggestions so an over-chatty critic doesn't derail context.
        verdict.suggestions = verdict.suggestions[: self.max_suggestions]
        return verdict

    def should_terminate(self, verdict: CriticVerdict) -> bool:
        """Autopilot asks this to decide whether to stop iterating."""
        if not verdict.criteria_met or not all(verdict.criteria_met):
            return False
        return verdict.confidence >= self.confidence_threshold

    # ── internals ────────────────────────────────────────────────

    def _build_prompt(self, *, objective: str, criteria: list[str], output: str) -> str:
        numbered = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(criteria))
        # Trim very long outputs — anything past ~6k chars gets summarized
        # by truncation. A stricter critic would summarize instead.
        trimmed = output if len(output) <= 6000 else output[:6000] + "\n…(truncated)"
        return (
            f"Objective: {objective}\n\n"
            f"Success criteria (respond in this order):\n{numbered}\n\n"
            f"Most recent agent output:\n---\n{trimmed}\n---\n"
        )

    def _complete(self, llm: Any, prompt: str) -> str:
        """Call whatever completion surface the LLM adapter exposes.

        Every shipit_agent adapter implements at least one of:
          - ``complete(messages=[...])``  → ``LLMResponse`` with ``.content``
          - ``generate(prompt=...)``      → plain string

        We try both so the critic stays decoupled from adapter internals.
        """
        try:
            from shipit_agent.models import Message

            resp = llm.complete(
                messages=[
                    Message(role="system", content=self.system_prompt),
                    Message(role="user", content=prompt),
                ]
            )
            # LLMResponse.content is canonical on this repo; fall back to str().
            return getattr(resp, "content", None) or str(resp)
        except AttributeError:
            pass
        if hasattr(llm, "generate"):
            return str(llm.generate(self.system_prompt + "\n\n" + prompt))
        # Last-resort: call the LLM like a function (rare test doubles do this).
        return str(llm(prompt))

    def _parse(self, raw: str, *, n_criteria: int) -> CriticVerdict:
        text = raw.strip()
        # Tolerate ```json fences — models often wrap despite the instruction.
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if fenced:
            text = fenced.group(1)
        # Find the first {...} JSON object.
        brace = text.find("{")
        if brace != -1:
            text = text[brace:]
            try:
                last = text.rindex("}")
                text = text[: last + 1]
            except ValueError:
                pass

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Even when the critic's output was garbage, we return a verdict
            # with criteria_met padded to n_criteria so downstream callers
            # don't have to special-case "is this the empty-skipped form?".
            return CriticVerdict(
                criteria_met=[False] * n_criteria,
                reasoning="critic returned non-JSON; skipped.",
            )

        met_raw = data.get("criteria_met") or []
        met: list[bool] = [bool(m) for m in met_raw][:n_criteria]
        # Normalize length to n_criteria — pad with False if short.
        if len(met) < n_criteria:
            met.extend([False] * (n_criteria - len(met)))

        confidence = float(data.get("confidence", 0.0) or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        suggestions = [str(s) for s in (data.get("suggestions") or []) if s]
        reasoning = str(data.get("reasoning", "")).strip()

        return CriticVerdict(
            criteria_met=met,
            confidence=confidence,
            suggestions=suggestions,
            reasoning=reasoning,
        )


# Utility exposed so Autopilot can feed suggestions into the next iteration.


def inject_suggestions_into_prompt(base_prompt: str, verdict: CriticVerdict) -> str:
    """Append a compact bullet list of critic suggestions to the prompt.

    Skip injection when nothing actionable was suggested so we don't clutter
    context with empty "(no feedback)" messages.
    """
    if not verdict.suggestions:
        return base_prompt
    lines = "\n".join(f"- {s}" for s in verdict.suggestions)
    return (
        f"{base_prompt}\n\n"
        f"[critic feedback from prior iteration — address these before concluding]\n"
        f"{lines}\n"
    )
