"""Helpers for creating and saving skills."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .registry import FileSkillRegistry
from .skill import Skill


def skill_id_from_name(name: str) -> str:
    """Create a stable slug-style skill id from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "custom-skill"


def create_skill(
    *,
    name: str,
    description: str,
    id: str | None = None,
    display_name: str | None = None,
    detailed_description: str = "",
    long_description: str = "",
    category: str = "",
    tags: list[str] | None = None,
    features: list[str] | None = None,
    use_cases: list[str] | None = None,
    how_to_use: list[str] | None = None,
    trigger_phrases: list[str] | None = None,
    tools: list[str] | None = None,
    prompt_template: str = "",
    requirements: list[str] | None = None,
    mcps: list[dict[str, Any]] | None = None,
    input_type: str = "text",
    output_type: str = "markdown",
    author: str = "local",
    version: str = "1.0.0",
    is_visible: bool = True,
    is_admin_enabled: bool = True,
    is_user_enabled: bool = True,
    featured: bool = False,
    premium: bool = False,
) -> Skill:
    """Create a Skill with practical defaults for local authoring."""
    skill_name = name.strip()
    return Skill(
        id=(id or skill_id_from_name(skill_name)),
        name=skill_name,
        display_name=display_name or skill_name,
        description=description.strip(),
        detailed_description=detailed_description.strip(),
        long_description=long_description.strip(),
        category=category.strip(),
        tags=list(tags or []),
        features=list(features or []),
        use_cases=list(use_cases or []),
        how_to_use=list(how_to_use or []),
        trigger_phrases=list(trigger_phrases or []),
        tools=list(tools or []),
        prompt_template=prompt_template.strip(),
        requirements=list(requirements or []),
        mcps=list(mcps or []),
        input_type=input_type,
        output_type=output_type,
        author=author,
        version=version,
        is_visible=is_visible,
        is_admin_enabled=is_admin_enabled,
        is_user_enabled=is_user_enabled,
        featured=featured,
        premium=premium,
    )


class SkillCatalog:
    """Create and persist skills in a local JSON catalog."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.registry = FileSkillRegistry(self.path)

    def list(self) -> list[Skill]:
        return self.registry.list()

    def get(self, skill_id: str) -> Skill | None:
        return self.registry.get(skill_id)

    def search(self, query: str) -> list[Skill]:
        return self.registry.search(query)

    def add(self, skill: Skill, *, overwrite: bool = True) -> Skill:
        existing = self.registry.get(skill.id)
        if existing is not None and not overwrite:
            raise ValueError(f"Skill '{skill.id}' already exists in {self.path}")
        self.registry.register(skill)
        self.registry.save()
        return skill

    def create(
        self,
        *,
        name: str,
        description: str,
        overwrite: bool = True,
        **kwargs: Any,
    ) -> Skill:
        skill = create_skill(name=name, description=description, **kwargs)
        return self.add(skill, overwrite=overwrite)

    def export(self) -> dict[str, Any]:
        skills = [skill.to_dict() for skill in self.registry.list()]
        return {"count": len(skills), "agents": skills}

    def as_path(self) -> Path:
        return self.path


__all__ = ["SkillCatalog", "create_skill", "skill_id_from_name"]
