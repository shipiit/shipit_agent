"""The base prompt and the general tool rules: every rule kept, nothing repeated.

Both are re-sent on every turn. After the per-tool guidance was cut, they
were most of the fixed prompt that was left (~2,200 and ~2,300 characters),
with whole rules said twice: "Quality bar" repeated "Core behavior", and
the tool rules repeated the base prompt's "use tools, don't simulate them".
The phrases pinned here are the rules themselves; the budget keeps them
from growing back into paragraphs.
"""

from __future__ import annotations

import pytest

from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.tools.helpers import TOOL_SECTION_HEADER
from shipit_agent.tools.todo.todo_tool import TodoTool
from shipit_agent.tools.tool_search.prompt import TOOL_SEARCH_PROMPT

BASE_RULES = [
    "end to end",                      # finish, don't stop at analysis
    "simulated call",                  # tool calls are structured, not prose
    "unless a tool result",            # no claims without evidence
    "verify important results",
    "uncertain",
    "repeating it",                    # change approach after a failure
    "before asking",                   # look before you ask
    "what you already looked at",
    "lead with the answer",
    "fenced",
    "path/to/file.py:42",
    "with the evidence",
]

TOOL_RULES = [
    "Call several tools in ONE response",
    "one at a time only when",
    "A search is the beginning of the work",
    "one result",                      # say so when an answer rests on one hit
    "Ask for what you need, not for everything",
    "Never repeat a call",
    "SAME response",
    "never stop after",
]


def _flat(text: str) -> str:
    """Lower-cased, with line wrapping undone, so a rule may wrap anywhere."""
    return " ".join(text.split()).lower()


@pytest.mark.parametrize("rule", BASE_RULES)
def test_the_base_prompt_keeps_each_rule(rule: str) -> None:
    assert rule.lower() in _flat(DEFAULT_AGENT_PROMPT)


@pytest.mark.parametrize("rule", TOOL_RULES)
def test_the_tool_section_keeps_each_rule(rule: str) -> None:
    assert rule.lower() in _flat(TOOL_SECTION_HEADER)


def test_quality_bar_is_merged_into_core_behaviour() -> None:
    assert "Quality bar" not in DEFAULT_AGENT_PROMPT


def test_tool_search_and_todo_keep_their_rules_without_the_repeated_sections() -> None:
    assert "When to use" not in TOOL_SEARCH_PROMPT
    for rule in ("intent", "already loaded", "never invent a tool", "same capability"):
        assert rule in TOOL_SEARCH_PROMPT
    todo = TodoTool().prompt_instructions
    for rule in ("three or more", "in_progress", "replaces the whole list"):
        assert rule in todo


def test_the_fixed_prompt_fits_its_budget() -> None:
    sizes = {"base": len(DEFAULT_AGENT_PROMPT), "tool rules": len(TOOL_SECTION_HEADER),
             "tool_search": len(TOOL_SEARCH_PROMPT), "todo": len(TodoTool().prompt_instructions)}
    # They were 2,227 + 2,288 + 868 + 590 characters.
    assert sum(sizes.values()) <= 4_000, sizes
