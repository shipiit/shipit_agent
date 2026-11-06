"""The todo checklist is for work with several steps, not a one-line fix.

A live run spent two of eleven calls writing and updating a five-item
checklist for a one-character bug. Claude Code's guidance draws the line
at three or more distinct steps and says to just do simple work.
"""

from __future__ import annotations

from shipit_agent.tools.todo.todo_tool import TodoTool


def test_the_guidance_says_when_to_use_the_list_and_when_to_skip_it() -> None:
    text = TodoTool().prompt_instructions.lower()
    assert "three or more" in text
    assert "skip" in text and "single" in text
