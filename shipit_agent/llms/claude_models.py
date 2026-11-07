"""What each Claude model accepts: output size, context, thinking and tool choice.

Claude models change their request surface between generations, and the change
is a hard 400 rather than a warning: a thinking budget is rejected from Claude
4.7 on, forced ``tool_choice`` from Opus 5.5 / Sonnet 5.5 / Fable 5.1 on. The
adapter reads these facts instead of sending one request shape to every model.

Rules are matched most-specific first, so ``claude-opus-5-5`` is never mistaken
for ``claude-opus-5``. Ids may carry a platform prefix (``anthropic.``,
``us.anthropic.``) or a date suffix; both are ignored. A model no rule knows
gets conservative facts: a small output cap and budget-style thinking, which
every older Claude accepts.

Source: Anthropic's model documentation, as of October 2026.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "ClaudeModel",
    "NON_STREAMING_OUTPUT_CAP",
    "STREAMING_OUTPUT_CAP",
    "claude_model",
    "known_claude_model",
]

#: Largest ``max_tokens`` worth asking for without streaming: bigger responses
#: risk the SDK's HTTP timeout before the model finishes.
NON_STREAMING_OUTPUT_CAP = 16_000

#: Default ``max_tokens`` for a streamed call: room for long answers and tool
#: inputs without asking every request for the model's full limit.
STREAMING_OUTPUT_CAP = 64_000


@dataclass(frozen=True, slots=True)
class ClaudeModel:
    """The request facts for one Claude model family."""

    max_output_tokens: int = 8_192
    context_window: int = 200_000
    #: ``adaptive``: ``thinking={"type": "adaptive"}`` with ``effort``.
    #: ``budget``: ``thinking={"type": "enabled", "budget_tokens": n}``.
    thinking: Literal["adaptive", "budget"] = "budget"
    #: A thinking budget returns a 400 instead of being ignored.
    rejects_thinking_budget: bool = False
    #: ``tool_choice`` ``any`` / ``tool`` is accepted.
    accepts_forced_tool_choice: bool = True


_NEWEST = ClaudeModel(
    max_output_tokens=128_000,
    context_window=1_000_000,
    thinking="adaptive",
    rejects_thinking_budget=True,
    accepts_forced_tool_choice=False,
)
_CURRENT = ClaudeModel(
    max_output_tokens=128_000,
    context_window=1_000_000,
    thinking="adaptive",
    rejects_thinking_budget=True,
)
_ADAPTIVE_WITH_BUDGET = ClaudeModel(
    max_output_tokens=128_000, context_window=1_000_000, thinking="adaptive"
)

_RULES: tuple[tuple[re.Pattern[str], ClaudeModel], ...] = (
    (re.compile(r"claude-(opus-5-5|sonnet-5-5|fable-5-1|mythos-5-1)\b"), _NEWEST),
    (
        re.compile(
            r"claude-(opus-5|sonnet-5|fable-5|mythos-5|opus-4-[78]|haiku-5-5)\b"
        ),
        _CURRENT,
    ),
    (re.compile(r"claude-(opus|sonnet)-4-6\b"), _ADAPTIVE_WITH_BUDGET),
    (re.compile(r"claude-(haiku|sonnet)-4-5\b"), ClaudeModel(max_output_tokens=64_000)),
)


def known_claude_model(model: str | None) -> ClaudeModel | None:
    """The facts for *model* when a rule knows it, else ``None``."""
    name = (model or "").lower()
    for pattern, facts in _RULES:
        if pattern.search(name):
            return facts
    return None


def claude_model(model: str) -> ClaudeModel:
    """The facts for *model*, or conservative defaults when no rule matches."""
    return known_claude_model(model) or ClaudeModel()
