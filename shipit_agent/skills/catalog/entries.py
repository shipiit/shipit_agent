"""What a listed skill is, and the catalog of them the prompt shows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)


LOAD_SKILL_TOOL_NAME = "load_skill"


SKILL_MESSAGE_SOURCE = "skill"


class SkillLike(Protocol):
    """The subset of a skill this module needs. Matches the existing dataclass."""

    id: str
    name: str
    description: str
    tools: list[str]

    def prompt_text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SkillCaps:
    """Ceilings, so a large registry cannot quietly blow the budget."""

    always_apply: int = 20
    manual: int = 10
    primed_per_turn: int = 30
    catalog_entries: int = 200
    description_chars: int = 120
    body_chars: int = 24_000


@dataclass(frozen=True, slots=True)
class PrimedSkill:
    """A skill whose body has entered the conversation."""

    id: str
    name: str
    body: str
    tools: tuple[str, ...]
    trigger: str  # "always_apply" | "manual" | "model"

    def as_message_payload(self) -> dict[str, Any]:
        """Shape for injection as a tail message, tagged for later filtering."""
        return {
            "role": "user",
            "content": self.body,
            "metadata": {
                "source": SKILL_MESSAGE_SOURCE,
                "skill_id": self.id,
                "skill_trigger": self.trigger,
            },
        }


def _summary(skill: SkillLike) -> str:
    text = getattr(skill, "description", "") or ""
    return " ".join(str(text).split())


def build_catalog(
    skills: Iterable[SkillLike],
    *,
    caps: SkillCaps | None = None,
    exclude: Iterable[str] = (),
) -> list[Any]:
    """Catalog entries for the stable prefix, sorted and capped.

    Returns ``SkillCatalogEntry`` values from :mod:`prefix`; imported lazily so
    this module stays usable on its own.
    """
    from shipit_agent.context.prefix import (
        SkillCatalogEntry,  # local import: avoids a hard cycle
    )

    caps = caps or SkillCaps()
    skipped = set(exclude)
    entries = [
        SkillCatalogEntry(
            id=skill.id,
            name=getattr(skill, "name", skill.id) or skill.id,
            description=_summary(skill)[: max(0, caps.description_chars)],
        )
        for skill in skills
        if skill.id and skill.id not in skipped
    ]
    entries.sort(key=lambda entry: entry.id)
    return entries[: caps.catalog_entries]
