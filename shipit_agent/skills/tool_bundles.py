"""Skill-to-tool bundle mapping for stronger runtime defaults.

Each entry maps a skill ID to the list of built-in tool names that
the skill needs at runtime.  When a skill is selected, the agent
automatically attaches these tools — so the LLM can actually act
on the skill's guidance without the caller having to wire tools
manually.

Keep tool names in sync with the default names in each tool class
(e.g. ``FileReadTool.name = "read_file"``).
"""

from __future__ import annotations

from .skill import Skill
from .tool_bundle_data import SKILL_TOOL_BUNDLES as SKILL_TOOL_BUNDLES


def tool_names_for_skills(skills: list[Skill]) -> list[str]:
    """Return a deduplicated, ordered list of tool names for the given skills.

    Merges tool names declared in each skill's ``tools`` list *and* the
    matching entry in ``SKILL_TOOL_BUNDLES``.
    """
    names: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        for name in [*skill.tools, *SKILL_TOOL_BUNDLES.get(skill.id, [])]:
            if name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


def validate_tool_bundles(builtin_names: set[str]) -> list[str]:
    """Check every tool name in SKILL_TOOL_BUNDLES against a known set.

    Returns a list of ``"skill_id: unknown_tool_name"`` strings for any
    references that do not appear in *builtin_names*.  An empty list
    means everything is valid.

    Usage::

        from shipit_agent.agent_setup.builtins import get_builtin_tool_map
        from shipit_agent.skills.tool_bundles import validate_tool_bundles
        errors = validate_tool_bundles(set(get_builtin_tool_map().keys()))
    """
    errors: list[str] = []
    for skill_id, tool_list in SKILL_TOOL_BUNDLES.items():
        for name in tool_list:
            if name not in builtin_names:
                errors.append(f"{skill_id}: {name}")
    return errors


__all__ = ["SKILL_TOOL_BUNDLES", "tool_names_for_skills", "validate_tool_bundles"]
