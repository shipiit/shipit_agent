"""Skill application and matching — the bridge between skills and agents.

This module provides three functions that the Agent uses at runtime:

- ``apply_skill(agent, skill)`` — injects a skill's prompt into the agent
- ``match_skill_by_trigger(registry, message)`` — exact trigger phrase match
- ``find_relevant_skills(registry, message)`` — activates authored triggers

Execution flow (called from ``Agent._selected_skills()``)::

    User prompt
        │
        └─→ match_skill_by_trigger()   # exact authored phrase
                "write release notes" → release-notes-writer

    Results are deduplicated by skill id and capped at ``max_skills``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .registry import SkillRegistry
from .skill import Skill

if TYPE_CHECKING:
    pass  # avoid circular imports with the main Agent class


def apply_skill(agent: Any, skill: Skill) -> None:
    """Merge a skill's prompt text into the agent's system prompt.

    The skill block is wrapped in HTML comment markers so it can be
    identified in the final prompt::

        <!-- skill:database-architect -->
        ...skill guidance and rules...
        <!-- /skill:database-architect -->

    Works with any object that has a ``prompt`` or ``system_prompt``
    attribute (Agent, DeepAgent, or a simple holder object).

    Raises ``ValueError`` if the agent has neither attribute.
    """
    template = skill.prompt_text()
    if not template:
        return

    block = f"\n\n<!-- skill:{skill.id} -->\n{template}\n<!-- /skill:{skill.id} -->\n"

    for attr in ("prompt", "system_prompt"):
        if hasattr(agent, attr):
            current = getattr(agent, attr) or ""
            setattr(agent, attr, current + block)
            return

    raise ValueError(
        f"Cannot apply skill — agent {agent!r} has no 'prompt' or 'system_prompt' attribute."
    )


def match_skill_by_trigger(
    registry: SkillRegistry,
    user_message: str,
) -> Skill | None:
    """Find the best skill whose trigger phrases appear in the user message.

    Scans every skill in the registry and counts how many of its
    ``trigger_phrases`` appear as substrings in *user_message* (case-
    insensitive). Returns the skill with the highest count, or ``None``
    if no trigger phrase matches at all.

    This is the highest-signal matching method — trigger phrases are
    explicitly authored to indicate when a skill should activate.
    """
    message_lower = user_message.lower()
    best_skill: Skill | None = None
    best_score: int = 0

    for skill in registry:
        score = 0
        for phrase in skill.trigger_phrases:
            pattern = rf"(?<!\w){re.escape(phrase.lower())}(?!\w)"
            if re.search(pattern, message_lower):
                score += 1
        if score > best_score:
            best_score = score
            best_skill = skill

    return best_skill


def find_relevant_skills(
    registry: SkillRegistry,
    user_message: str,
    *,
    max_skills: int = 3,
) -> list[Skill]:
    """Return the most relevant skills for a user message.

    Uses authored trigger phrases for automatic activation. Fuzzy catalog
    search remains available through ``SkillRegistry.search()`` for explicit
    discovery, but is intentionally excluded here: weak token overlap can
    silently add large, unrelated prompt and tool bundles to every LLM turn.

    Results are deduplicated by skill id and capped at *max_skills*.

    Called by ``Agent._selected_skills()`` when ``auto_use_skills=True``.
    """
    selected: list[Skill] = []
    seen_ids: set[str] = set()

    # 1. Try direct trigger match first (highest signal).
    direct = match_skill_by_trigger(registry, user_message)
    if direct is not None:
        selected.append(direct)
        seen_ids.add(direct.id)

    return selected[:max_skills]
