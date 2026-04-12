"""Skills subsystem — discover, register, and apply agent skills."""

from .authoring import SkillCatalog, create_skill, skill_id_from_name
from .loader import apply_skill, find_relevant_skills, match_skill_by_trigger
from .registry import FileSkillRegistry, SkillRegistry
from .skill import Skill

__all__ = [
    "FileSkillRegistry",
    "SkillCatalog",
    "Skill",
    "SkillRegistry",
    "apply_skill",
    "create_skill",
    "find_relevant_skills",
    "match_skill_by_trigger",
    "skill_id_from_name",
]
