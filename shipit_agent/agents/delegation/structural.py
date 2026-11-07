"""Judging from the prompt's shape alone: lists, counts and breadth words."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .advice import DelegationAdvice

# ── structural ────────────────────────────────────────────────────────────

# Enumerations: "1. …", "- …", "* …" — a work list the author wrote out.
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.MULTILINE)
# Concrete targets: anything with a file extension, a quoted name, or a URL.
# Structure, not vocabulary — a path is a path in every language.
_TARGET = re.compile(
    r"""(?:
        [\w./-]+\.[A-Za-z][\w]{1,5}\b       # a.py, notes.md, data.csv
      | https?://\S+                        # a URL
      | ["'`][^"'`\n]{2,60}["'`]            # a quoted name
    )""",
    re.VERBOSE,
)
# An explicit quantity: "12 reports", "twelve incidents".
_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "dozen": 12, "twenty": 20, "fifty": 50, "hundred": 100,
}
# A number, then a plural head within a word or two of it — "twelve incident
# reports" and "12 open PRs" both count, "12 hours ago" does not.
_QUANTITY = re.compile(
    r"\b(\d{1,4}|" + "|".join(_NUMBER_WORDS) + r")\s+(?:[a-z-]+\s+){0,2}[a-z]{3,}s\b",
    re.IGNORECASE,
)


# Breadth: a distributive determiner over a noun — "every document",
# "each of the repos", "all the open PRs". Grammar rather than vocabulary,
# so it holds for wording nobody anticipated. The count is unknown, which is
# the point: "go through every document attached" names no number and no
# filename, and is exactly the work that should be split.
_BREADTH = re.compile(
    r"\b(?:every|each|all)\s+(?:of\s+)?(?:the\s+|your\s+|our\s+|my\s+)?"
    r"(?:[a-z-]+\s+){0,2}[a-z]{3,}\b",
    re.IGNORECASE,
)
# …but not when the "all" is an adverb or an idiom rather than a scope.
_NOT_BREADTH = re.compile(
    r"\ball\s+(?:right|good|set|done|clear|about|along|over|"
    r"the\s+same|of\s+it|of\s+this|of\s+that)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class StructuralAssessor:
    """Count the structure of a task: lists, targets, stated quantities.

    Used when there is no model to ask, and as the floor under
    :class:`ModelAssessor` — if the task literally enumerates eight files, a
    model that says "one piece of work" is wrong and is overruled.
    """

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice:
        if not prompt:
            return DelegationAdvice(False, source="structural")
        reasons: list[str] = []

        listed = len(_LIST_ITEM.findall(prompt))
        if listed:
            reasons.append(f"the task enumerates {listed} items")

        targets = len({match.group(0) for match in _TARGET.finditer(prompt)})
        if targets > 1:
            reasons.append(f"{targets} concrete targets are named")

        quantities = [
            int(value) if value.isdigit() else _NUMBER_WORDS[value.lower()]
            for value in _QUANTITY.findall(prompt)
        ]
        stated = max(quantities, default=0)
        if stated > 1:
            reasons.append(f"the task states a quantity of {stated}")

        # Breadth carries no number — "every document attached" could be two
        # or twenty. It still separates, so it counts as a reason to
        # delegate without inflating the count with a guess.
        broad = bool(_BREADTH.search(prompt)) and not _NOT_BREADTH.search(prompt)
        if broad:
            reasons.append("the task applies to every item in a set")

        items = max(listed, targets, stated)
        return DelegationAdvice(items > 1 or broad, items=items,
                                reasons=reasons, source="structural")
