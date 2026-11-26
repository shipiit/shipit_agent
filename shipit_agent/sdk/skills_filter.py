"""``AgentOptions(skills=...)``: which of the discovered skills the main agent may use."""

from __future__ import annotations

import copy
import re
from typing import Any

__all__ = ["limit_skills"]

#: An exact skill name: letters, digits, ``-``, ``_``, ``.`` and ``:``; no wildcards or paths.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _names(spec: Any) -> list[str]:
    if not isinstance(spec, list) or not all(isinstance(name, str) and _NAME.match(name) for name in spec):
        raise ValueError('skills must be None, "all" or a list of exact skill names (no wildcards)')
    return list(spec)


def limit_skills(agent: Any, spec: Any) -> None:
    """Keep only the named skills in the agent's registry; ``None`` and ``"all"`` keep every one.

    A skill is matched by its id or its name. The registry is copied, so one
    shared by other agents is left whole.
    """
    if spec is None or spec == "all":
        return
    wanted = _names(spec)
    registry = agent.skill_registry
    skills = registry.list() if registry is not None else []
    known = {key: skill for skill in skills for key in (skill.id, skill.name) if key}
    missing = [name for name in wanted if name not in known]
    if missing:
        available = ", ".join(sorted(skill.name or skill.id for skill in skills)) or "none were found"
        raise ValueError(f"skills: no skill named {', '.join(missing)} (available: {available})")
    if registry is None:
        return
    kept = {known[name].id for name in wanted}
    limited = copy.copy(registry)
    limited._skills = {skill.id: skill for skill in skills if skill.id in kept}
    agent.skill_registry = limited
