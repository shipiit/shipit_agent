"""Asking the model whether a task splits into independent parts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .advice import DelegationAdvice
from .structural import StructuralAssessor

# ── model ─────────────────────────────────────────────────────────────────

_ASSESS_PROMPT = """\
You are sizing a task for an agent that can delegate work to sub-agents.

Count only the pieces the task ITSELF names — files it lists, targets it
enumerates, a quantity it states. Do not invent a decomposition: almost any
task *could* be split some way, and imagining one is how a single question
turns into five agents doing worse than one.

Say false for anything a single tool call answers. "Look for the latest AI
news" is one search, not one per topic. "Read the file and summarise it" is
one read. Delegating those costs an extra model call each and loses
everything the child saw.

Say true when the task names several independent pieces AND their material
(long files, wide searches, many records) does not need to be in one place.

TASK:
{task}

Answer with JSON and nothing else:
{{"decompose": true|false, "items": <pieces the task names, 0 if none>,
 "reason": "<one clause, under 12 words>"}}\
"""


@dataclass(slots=True)
class ModelAssessor:
    """Ask the agent's own LLM whether its task decomposes.

    One short completion with no tools. Results are cached per task string,
    so re-running the same prompt costs nothing, and any failure — no model,
    a timeout, unparseable output — falls back to
    :class:`StructuralAssessor` rather than blocking the run.
    """

    min_items: int = 2
    _cache: dict[str, DelegationAdvice] = field(default_factory=dict)

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice:
        structural = StructuralAssessor().assess(prompt)
        if llm is None or not prompt:
            return structural
        if prompt in self._cache:
            return self._cache[prompt]

        verdict = self._ask(llm, prompt)
        if verdict is None:
            return structural

        decompose, items, reason = verdict
        reasons = [reason] if reason else []
        # The structural floor: a task that names eight files has eight
        # pieces whatever the model says about it.
        if structural.items > items:
            items = structural.items
            reasons += structural.reasons
        # The floor works both ways. It has always raised a model that
        # undercounted a task naming eight files; it now also declines a
        # model that invents pieces the task never mentioned. Gemma 4 on
        # "Can you look for the latest AI news?" answered `decompose: true,
        # items: 3, "news can be split by topic or source"` — three agents
        # for one search, and none of those topics appear in the request.
        # A yes has to be corroborated by something actually in the text.
        delegate = bool(decompose) or items >= max(2, self.min_items)
        if delegate and not structural and not structural.items:
            delegate = False
            # The count stays — it is what the model saw, and useful when
            # someone asks why. Only the verdict is overruled.
            reasons = ["the task names no separable pieces"] + reasons
        advice = DelegationAdvice(
            delegate=delegate,
            items=items,
            reasons=reasons or structural.reasons,
            source="model",
        )
        self._cache[prompt] = advice
        return advice

    @staticmethod
    def _ask(llm: Any, prompt: str) -> tuple[bool, int, str] | None:
        from shipit_agent.core.models import Message

        try:
            response = llm.complete(
                messages=[Message(role="user", content=_ASSESS_PROMPT.format(
                    task=prompt[:4000]))],
                tools=[],
            )
            payload = _first_json_object(str(getattr(response, "content", "") or ""))
        except Exception:
            return None
        if payload is None:
            return None
        try:
            return (
                bool(payload.get("decompose")),
                int(payload.get("items") or 0),
                str(payload.get("reason") or "")[:120],
            )
        except (TypeError, ValueError):
            return None


def _first_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a reply, however the model wrapped it.

    Small models fence it, prefix it, or add a sentence afterwards; none of
    that should cost a delegation decision.
    """
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                except ValueError:
                    start = -1
                    continue
                if isinstance(value, dict):
                    return value
    return None
