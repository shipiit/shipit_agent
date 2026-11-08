"""Prompts GoalAgent uses to decompose and evaluate a goal."""

from __future__ import annotations

DECOMPOSE_PROMPT = """You are a goal-oriented agent. Break this goal into ordered sub-tasks.

Goal: {objective}

Success criteria:
{criteria}

Respond with JSON: {{"subtasks": ["task 1", "task 2", ...]}}"""


EVALUATE_PROMPT = """Evaluate whether each criterion is met based on the work done so far.

Goal: {objective}

Success criteria:
{criteria}

Work completed:
{work}

Respond with JSON: {{"criteria_met": [true, false, ...], "all_done": true/false, "next_action": "what to do next"}}"""

