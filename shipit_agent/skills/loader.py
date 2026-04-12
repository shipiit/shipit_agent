"""Helpers for applying skills to agents and matching user messages to skills."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .registry import SkillRegistry
from .skill import Skill

if TYPE_CHECKING:
    pass  # avoid circular imports with the main Agent class


def apply_skill(agent: Any, skill: Skill) -> None:
    """Merge *skill*'s ``prompt_template`` into *agent*'s prompt.

    The function appends the skill prompt block to the agent's existing
    ``prompt`` attribute (or ``system_prompt``, whichever exists).  If the
    agent exposes neither, a ``ValueError`` is raised.
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
    """Find the best matching skill whose trigger phrases appear in *user_message*.

    Returns the skill with the highest number of matching trigger phrases, or
    ``None`` if no trigger phrase matches.
    """
    message_lower = user_message.lower()
    best_skill: Skill | None = None
    best_score: int = 0

    for skill in registry:
        score = 0
        for phrase in skill.trigger_phrases:
            if phrase.lower() in message_lower:
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

    We combine exact trigger matching with registry search so broad
    marketplace-style skill catalogs still produce useful matches.
    """
    selected: list[Skill] = []
    seen_ids: set[str] = set()

    direct = match_skill_by_trigger(registry, user_message)
    if direct is not None:
        selected.append(direct)
        seen_ids.add(direct.id)

    for skill in registry.search(user_message):
        if skill.id in seen_ids:
            continue
        selected.append(skill)
        seen_ids.add(skill.id)
        if len(selected) >= max_skills:
            break

    return selected[:max_skills]
