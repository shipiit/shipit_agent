"""A run's skills: which are listed, which are loaded, and what loading one adds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .entries import PrimedSkill, SkillCaps, SkillLike, logger


@dataclass
class SkillSession:
    """Which skills are loaded for this run, and what they unlocked.

    Owns the whole mutable skill state so it can be checkpointed as one object
    and restored on resume — a run that primed three skills before pausing must
    come back with those three still primed, or it silently loses capability.
    """

    caps: SkillCaps = field(default_factory=SkillCaps)
    #: Tool names available before any skill widened the set.
    base_tools: frozenset[str] = frozenset()
    primed: dict[str, PrimedSkill] = field(default_factory=dict)
    #: Names a skill asked for that this deployment does not provide.
    unmet_tools: set[str] = field(default_factory=set)

    # -- queries -----------------------------------------------------------

    @property
    def allowed_tools(self) -> frozenset[str]:
        """Base tools plus every tool unlocked by a primed skill."""
        unlocked: set[str] = set(self.base_tools)
        for skill in self.primed.values():
            unlocked.update(skill.tools)
        return frozenset(unlocked)

    def is_primed(self, skill_id: str) -> bool:
        return skill_id in self.primed

    def at_capacity(self) -> bool:
        return len(self.primed) >= self.caps.primed_per_turn

    # -- mutation ----------------------------------------------------------

    def prime(
        self,
        skill: SkillLike,
        *,
        trigger: str = "model",
        available_tools: Iterable[str] | None = None,
    ) -> PrimedSkill | None:
        """Load *skill*'s body and widen the tool set. Idempotent.

        Returns ``None`` when the skill was already primed or the per-turn cap
        is reached — both are ordinary outcomes, not errors, and the caller
        reports them to the model as a result rather than raising.
        """
        if skill.id in self.primed:
            return None
        if self.at_capacity():
            logger.debug(
                "Skill cap reached (%d); not priming %s",
                self.caps.primed_per_turn,
                skill.id,
            )
            return None

        body = (skill.prompt_text() or "").strip()
        if len(body) > self.caps.body_chars:
            body = body[: self.caps.body_chars].rstrip() + "\n\n[skill body truncated]"

        declared = [str(name) for name in (getattr(skill, "tools", None) or [])]
        if available_tools is None:
            granted = declared
        else:
            provided = set(available_tools)
            granted = [name for name in declared if name in provided]
            missing = [name for name in declared if name not in provided]
            if missing:
                # Dropped, never fatal: a skill authored against another
                # agent's toolset must still import and still be useful.
                self.unmet_tools.update(missing)
                logger.debug(
                    "Skill %s declares unavailable tools: %s",
                    skill.id,
                    ", ".join(sorted(missing)),
                )

        primed = PrimedSkill(
            id=skill.id,
            name=getattr(skill, "name", skill.id) or skill.id,
            body=body,
            tools=tuple(granted),
            trigger=trigger,
        )
        self.primed[skill.id] = primed
        return primed

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_tools": sorted(self.base_tools),
            "unmet_tools": sorted(self.unmet_tools),
            "primed": [
                {
                    "id": s.id,
                    "name": s.name,
                    "body": s.body,
                    "tools": list(s.tools),
                    "trigger": s.trigger,
                }
                for s in self.primed.values()
            ],
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, caps: SkillCaps | None = None
    ) -> "SkillSession":
        session = cls(
            caps=caps or SkillCaps(),
            base_tools=frozenset(data.get("base_tools") or ()),
            unmet_tools=set(data.get("unmet_tools") or ()),
        )
        for entry in data.get("primed") or ():
            skill = PrimedSkill(
                id=str(entry.get("id", "")),
                name=str(entry.get("name", "")),
                body=str(entry.get("body", "")),
                tools=tuple(entry.get("tools") or ()),
                trigger=str(entry.get("trigger", "model")),
            )
            if skill.id:
                session.primed[skill.id] = skill
        return session
