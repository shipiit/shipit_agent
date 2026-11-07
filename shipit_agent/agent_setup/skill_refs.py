"""How an agent refers to skills: the packaged catalog, and a skill or its id."""

from __future__ import annotations

from pathlib import Path

from shipit_agent.skills import Skill

# The packaged skills catalog, shipped with the library.
DEFAULT_SKILLS_PATH = Path(__file__).resolve().parent.parent / "skills" / "skills.json"

# A skill reference: a resolved ``Skill``, or an id looked up in the registry.
SkillLike = str | Skill
