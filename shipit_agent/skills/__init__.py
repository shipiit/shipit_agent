"""Skills subsystem — discover, register, and apply agent skills."""

from .authoring import SkillCatalog, create_skill, skill_id_from_name
from .loader import apply_skill, find_relevant_skills, match_skill_by_trigger
from .registry import (
    FileSkillRegistry,
    SkillRegistry,
    discover_project_skills,
    load_markdown_skill,
)
from .skill import Skill

__all__ = [
    "FileSkillRegistry",
    "SkillCatalog",
    "Skill",
    "SkillRegistry",
    "apply_skill",
    "create_skill",
    "discover_project_skills",
    "find_relevant_skills",
    "match_skill_by_trigger",
    "load_markdown_skill",
    "skill_id_from_name",
]
