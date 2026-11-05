"""Which skills a run uses: the explicit ones, triggered ones, and the on-demand catalog.

Mixed into :class:`~shipit_agent.agent.Agent` through
:class:`~shipit_agent.agent_setup.preparation.AgentPreparationMixin`.
"""

from __future__ import annotations

from shipit_agent.skills import Skill, find_relevant_skills
from shipit_agent.skills.tool_bundles import tool_names_for_skills

SkillLike = str | Skill


def _triggered(skill: Skill, prompt: str) -> bool:
    """Whether *prompt* contains one of *skill*'s trigger phrases as whole words."""
    import re

    text = prompt.lower()
    return any(
        re.search(rf"\b{re.escape(phrase.lower())}\b", text)
        for phrase in getattr(skill, "trigger_phrases", None) or ()
        if phrase.strip()
    )


class SkillSelectionMixin:
    """Which skills a run uses: the explicit ones, triggered ones, and the on-demand catalog."""

    def _resolve_skill_ref(self, skill_ref: SkillLike) -> Skill:
        if isinstance(skill_ref, Skill):
            return skill_ref
        if self.skill_registry is None:
            raise ValueError(
                f"Cannot resolve skill '{skill_ref}' because no skill registry "
                "is configured."
            )
        skill = self.skill_registry.get(skill_ref)
        if skill is None:
            raise ValueError(f"Unknown skill id: {skill_ref}")
        return skill

    def _selected_skills(self, user_prompt: str) -> list[Skill]:
        selected: list[Skill] = []
        seen: set[str] = set()
        candidates = [*self.skills]
        candidates.extend(self._resolve_skill_ref(i) for i in self.default_skill_ids)
        if self.auto_use_skills and self.progressive_skills:
            # On demand, the model chooses from the catalog; only a skill's own
            # exact trigger phrase primes it without a model turn.
            candidates.extend(
                skill
                for skill in self._listed_skills()
                if _triggered(skill, user_prompt)
            )
        if (
            self.auto_use_skills
            and not self.progressive_skills
            and self.skill_registry is not None
        ):
            candidates.extend(
                find_relevant_skills(
                    self.skill_registry,
                    user_prompt,
                    max_skills=self.skill_match_limit,
                )
            )
        for skill in candidates:
            if skill.id not in seen:
                selected.append(skill)
                seen.add(skill.id)
        return selected

    def _progressive_skill_catalog(self, selected_skills):
        if not self.progressive_skills or self.skill_registry is None:
            return []
        from shipit_agent.skills.catalog import build_catalog

        return build_catalog(
            self._listed_skills(), exclude=[skill.id for skill in selected_skills]
        )

    def _listed_skills(self) -> list[Skill]:
        """The skills an on-demand catalog offers the model.

        The project's SKILL.md files and any registry the caller supplied;
        the packaged catalog only with ``advertise_packaged_skills``.
        """
        if self.skill_registry is None:
            return []
        listed = [
            skill
            for skill in self.skill_registry.list()
            if skill.is_visible and skill.is_admin_enabled and skill.is_user_enabled
        ]
        if self._is_packaged_registry() and not self.advertise_packaged_skills:
            project_ids = self._project_skill_ids()
            listed = [skill for skill in listed if skill.id in project_ids]
        return listed

    def _is_packaged_registry(self) -> bool:
        """Whether the registry is the library's packaged catalog file."""
        from pathlib import Path

        from shipit_agent.agent_setup.settings import DEFAULT_SKILLS_PATH
        from shipit_agent.skills import FileSkillRegistry

        registry = self.skill_registry
        return isinstance(registry, FileSkillRegistry) and (
            Path(registry.path).resolve() == DEFAULT_SKILLS_PATH.resolve()
        )

    def _project_skill_ids(self) -> set[str]:
        """Ids of the SKILL.md files discovered in the project."""
        if not self.auto_project_skills:
            return set()
        from shipit_agent.skills import discover_project_skills

        return {skill.id for skill in discover_project_skills(self.project_root)}

    def _skill_tool_names(self, selected_skills: list[Skill]) -> list[str]:
        available = {getattr(tool, "name", None) for tool in self.tools}
        names: list[str] = []
        for name in tool_names_for_skills(selected_skills):
            if name not in available and name not in names:
                names.append(name)
        return names
