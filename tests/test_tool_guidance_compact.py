"""The core tools' guidance keeps the rules that prevent mistakes, and only those.

Each tool's guidance is printed in the system prompt and re-sent on every
turn. It carried "When to use", "Decision tree", "Workflow" and
"Anti-patterns" sections that repeated each other and the tool's
description: about 3,300 tokens a turn for the default agent. The rules
pinned below are the ones that stop a real failure (an edit on an unread
file, a line-number prefix copied into old_text, a refused command retried
in another form), so they must survive any trim.
"""

from __future__ import annotations

import pytest

from shipit_agent.tools.bash.prompt import BASH_PROMPT
from shipit_agent.tools.edit_file.prompt import EDIT_FILE_PROMPT
from shipit_agent.tools.file_read.prompt import FILE_READ_PROMPT
from shipit_agent.tools.file_write.prompt import FILE_WRITE_PROMPT
from shipit_agent.tools.glob_search.prompt import GLOB_SEARCH_PROMPT
from shipit_agent.tools.grep_search.prompt import GREP_SEARCH_PROMPT
from shipit_agent.tools.web_search.prompt import WEB_SEARCH_PROMPT

GUIDANCE = {
    "read_file": FILE_READ_PROMPT,
    "edit_file": EDIT_FILE_PROMPT,
    "write_file": FILE_WRITE_PROMPT,
    "bash": BASH_PROMPT,
    "glob_files": GLOB_SEARCH_PROMPT,
    "grep_files": GREP_SEARCH_PROMPT,
    "web_search": WEB_SEARCH_PROMPT,
}

#: Phrases each tool's guidance must still contain (case-insensitive).
RULES = {
    "read_file": ["start_line", "max_lines", ".docx", "before"],
    "edit_file": ["read the file first", "exactly", "line-number prefix", "replace_all", "write_file"],
    "write_file": ["edit_file", "read the existing file first"],
    # A live run spent its first call on `python3 test_cart.py`, which runs no tests.
    "bash": ["pytest -q", "npm test", "read_file", "grep_files", "edit_file", "approval", "do not retry", "bash_job",
             "background: true", "working_directory", "&&"],
    "glob_files": ["**/*.py", "grep_files"],
    "grep_files": ["glob", "regex", "case_sensitive", "max_matches"],
    "web_search": ["open_url", "do not guess"],
}

REPEATED_SECTIONS = ("When to use", "Decision tree", "Workflow", "Anti-patterns", "Common patterns")


@pytest.mark.parametrize("tool", sorted(GUIDANCE))
def test_the_rules_that_prevent_mistakes_are_kept(tool: str) -> None:
    text = GUIDANCE[tool].lower()
    missing = [rule for rule in RULES[tool] if rule.lower() not in text]
    assert not missing, f"{tool} lost {missing}"


@pytest.mark.parametrize("tool", sorted(GUIDANCE))
def test_the_repeated_sections_are_gone(tool: str) -> None:
    present = [s for s in REPEATED_SECTIONS if s in GUIDANCE[tool]]
    assert not present, f"{tool} still has {present}"


def test_the_guidance_fits_its_budget() -> None:
    # About 4 characters a token: the seven together were ~10,300 characters.
    sizes = {tool: len(text) for tool, text in GUIDANCE.items()}
    assert sum(sizes.values()) <= 5_200, sizes
    assert all(size <= 1_300 for size in sizes.values()), sizes
