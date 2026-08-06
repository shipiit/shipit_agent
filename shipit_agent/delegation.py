"""Automatic delegation — the agent reaches for sub-agents on its own.

Handing work to a sub-agent is the difference between an agent that reads
twenty files into one context and an agent that reads twenty files in twenty
contexts and keeps only the summaries. Left to a plain prompt, a model does
this rarely: the tool exists, the guidance is a paragraph in the system
prompt, and the straight path is right there.

This module makes it a policy::

    agent = Agent(llm=llm, tools=[...], delegation=True)
    agent.run("Summarize each of the twelve incident reports in reports/.")

Three decisions, each of which was measured rather than assumed:

**The tool is guaranteed to exist.** If the agent has no ``sub_agent``, one
is built from the agent's own LLM and its read-only tools.

**The task is assessed by a model, not by a word list.** A keyword table is a
guess about one language's phrasing that goes stale the moment someone writes
"handle these tickets" instead of "for each ticket". :class:`ModelAssessor`
asks the LLM a single cheap question about the task and gets back a count and
a reason. :class:`StructuralAssessor` is the fallback when there is no model
to ask: it counts *structure* — enumerated lists, distinct concrete targets,
explicit quantities — never vocabulary.

**The directive goes in the task, not the system prompt.** Measured against
Gemma 4 on Bedrock with three reports to summarize: system prompt → 0
delegations, same text appended to the task → 6. A small model treats the
system prompt as background and the task as instructions.

What this deliberately does **not** do is delegate behind the model's back.
The runtime cannot know which parts of a task are independent, and guessing
would spawn sub-agents working on halves of an indivisible problem. The model
still decides — with the tool present and the case put in the right place.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "Assessor",
    "DelegationAdvice",
    "DelegationPolicy",
    "ModelAssessor",
    "StructuralAssessor",
    "coerce_delegation",
]


@dataclass(slots=True)
class DelegationAdvice:
    """Whether this task looks like sub-agent work, and why.

    ``reasons`` is evidence, not decoration: it goes into the directive, so
    the model is told what was noticed rather than nagged in the abstract.
    """

    delegate: bool
    items: int = 0
    reasons: list[str] = field(default_factory=list)
    source: str = ""

    def __bool__(self) -> bool:
        return self.delegate


class Assessor(Protocol):
    """Decides whether a task decomposes. Swap in your own if you like."""

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice: ...


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

        items = max(listed, targets, stated)
        return DelegationAdvice(items > 1, items=items,
                                reasons=reasons, source="structural")


# ── model ─────────────────────────────────────────────────────────────────

_ASSESS_PROMPT = """\
You are sizing a task for an agent that can delegate work to sub-agents.

A sub-agent is a separate agent with its own context. Delegating pays off
when a task splits into pieces that can be worked on independently and whose
intermediate material (long files, wide searches, many records) does not need
to be in one place. It costs more than it saves for a single lookup, a single
edit, or work where every step depends on the last.

TASK:
{task}

Answer with JSON and nothing else:
{{"decompose": true|false, "items": <how many independent pieces, 0 if none>,
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
        advice = DelegationAdvice(
            delegate=bool(decompose) or items >= max(2, self.min_items),
            items=items,
            reasons=reasons or structural.reasons,
            source="model",
        )
        self._cache[prompt] = advice
        return advice

    @staticmethod
    def _ask(llm: Any, prompt: str) -> tuple[bool, int, str] | None:
        from shipit_agent.models import Message

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


# ── policy ────────────────────────────────────────────────────────────────


@dataclass
class DelegationPolicy:
    """When to push the agent toward sub-agents, and how hard.

    ``assessor`` decides whether a task decomposes — :class:`ModelAssessor`
    by default (one cheap call, cached), :class:`StructuralAssessor` for a
    zero-cost approximation, or anything implementing :class:`Assessor`.

    ``attach_tool`` builds a ``sub_agent`` when the agent has none; turn it
    off to supply your own — a narrower toolset, a cheaper model for the
    children, a lower iteration cap.
    """

    enabled: bool = True
    min_items: int = 2
    attach_tool: bool = True
    max_iterations: int = 6
    max_workers: int = 4
    assessor: Any = None
    # Children get read-only tools by default: a sub-agent that can write is
    # a side effect you did not review, from a decision you did not see.
    child_tools: list[Any] | None = None
    read_only_children: bool = True

    def __post_init__(self) -> None:
        if self.assessor is None:
            self.assessor = ModelAssessor(min_items=self.min_items)

    # ── assessment ───────────────────────────────────────────────────────

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice:
        """Read the task and decide whether it wants delegating."""
        if not self.enabled or not prompt:
            return DelegationAdvice(False)
        advice = self.assessor.assess(prompt, llm=llm)
        if advice.items and advice.items < self.min_items:
            return DelegationAdvice(False, items=advice.items,
                                    reasons=advice.reasons, source=advice.source)
        return advice

    # ── the directive ────────────────────────────────────────────────────

    def directive(self, advice: DelegationAdvice) -> str:
        """The instruction appended to the *task* for this run.

        Appended to the task rather than the system prompt on purpose: a
        small model reads the system prompt as background and the task as
        instructions, and the difference is measurable (see the module
        docstring).
        """
        if not advice:
            return ""
        because = "; ".join(advice.reasons) or "it has independent parts"
        count = f"about {advice.items}" if advice.items > 1 else "several"
        return (
            "\n\n---\n"
            f"This task has {count} separable pieces — {because}. "
            "Work it that way:\n"
            "- Send **each piece** to `sub_agent`, with a task naming the one "
            "thing it must do and the exact shape of the answer you want back.\n"
            "- Run independent pieces at once: `background=true` starts one, "
            '`collect="<id>"` fetches its result. Collect every one of them '
            "before you answer — the run ends with your answer, so a task "
            "left uncollected is simply lost, and promising the user a "
            "later report is promising something that cannot happen.\n"
            "- Do not read the material yourself. The point of a sub-agent is "
            "that what it read never enters your context — only its answer does.\n"
            "- Combine the answers yourself; do not delegate the combining."
        )

    def apply(self, task: str, *, llm: Any = None) -> str:
        """The task, with the directive appended when it is warranted."""
        return task + self.directive(self.assess(task, llm=llm))

    # ── tool ─────────────────────────────────────────────────────────────

    def build_tool(self, llm: Any, tools: list[Any]) -> Any | None:
        """A ``sub_agent`` for this agent, or ``None`` if one is unwarranted."""
        if not self.enabled or not self.attach_tool or llm is None:
            return None
        from shipit_agent.tools.sub_agent import SubAgentTool

        child_tools = self.child_tools
        if child_tools is None and self.read_only_children:
            from shipit_agent.permissions import PermissionEngine

            engine = PermissionEngine()
            child_tools = [
                tool
                for tool in tools
                if engine.is_read_only(getattr(tool, "name", ""), tool)
            ] or None
        return SubAgentTool(
            llm=llm,
            tools=child_tools,
            max_iterations=self.max_iterations,
            max_workers=self.max_workers,
        )


def coerce_delegation(spec: Any) -> DelegationPolicy | None:
    """Normalize ``delegation=`` — a policy, ``True``, a dict, or ``None``."""
    if spec is None or spec is False:
        return None
    if isinstance(spec, DelegationPolicy):
        return spec if spec.enabled else None
    if spec is True:
        return DelegationPolicy()
    if isinstance(spec, dict):
        return DelegationPolicy(**spec)
    raise TypeError(f"Unsupported delegation spec: {type(spec)!r}")
