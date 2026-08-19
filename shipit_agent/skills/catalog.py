"""Skills the model can reach for mid-run, instead of ones chosen for it.

Selecting skills up front by matching trigger phrases against the first user
message has three costs. A request phrased differently from the authored
triggers activates nothing. A need that only becomes apparent at iteration four
— the file turns out to be a tracked-changes DOCX — can never be served, because
selection already happened. And injecting full skill bodies into the system
prompt makes each skill expensive enough that the count has to be capped low,
and moves the prompt prefix, which costs every subsequent cache hit.

Progressive disclosure fixes all three:

* the **catalog** — one line per skill, id plus a summary — sits in the stable
  prefix and costs roughly ten tokens per skill, so hundreds fit;
* the **body** is loaded only when the model calls ``load_skill``, at whatever
  iteration it decides it needs one, and arrives as a message in the volatile
  tail where it cannot disturb the cached prefix;
* loading a skill **widens the run's allowed tool set** to whatever that skill
  declares, so a skill can carry tools without every run paying for them.

Three trigger classes coexist, because each answers a different question:
``always_apply`` ("this agent is always this kind of agent"), ``manual``
("this phrasing means this skill", the fast path that needs no model turn), and
``model`` ("the model decided"). A skill naming a tool this deployment does not
have is loaded anyway with that tool dropped and a debug line — that is what
lets skills authored against another toolset import without breaking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "SkillLike",
    "SkillCaps",
    "PrimedSkill",
    "SkillSession",
    "build_catalog",
    "LoadSkillTool",
    "LOAD_SKILL_TOOL_NAME",
    "SKILL_MESSAGE_SOURCE",
]

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
    from shipit_agent.prefix import SkillCatalogEntry  # local import: avoids a hard cycle

    caps = caps or SkillCaps()
    skipped = set(exclude)
    entries = [
        SkillCatalogEntry(
            id=skill.id,
            name=getattr(skill, "name", skill.id) or skill.id,
            description=_summary(skill),
        )
        for skill in skills
        if skill.id and skill.id not in skipped
    ]
    entries.sort(key=lambda entry: entry.id)
    return entries[: caps.catalog_entries]


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


class LoadSkillTool:
    """The tool that turns a catalog line into working instructions.

    Deliberately thin: it looks a skill up, primes it, and returns the body as
    the tool result. Returning the body *as the result* is what puts it in the
    volatile tail rather than the cached prefix, and what makes the load visible
    in the trace like any other tool call.

    Failure modes are results, not exceptions — an unknown id returns the
    nearest matches so the model can correct itself in one turn instead of
    failing the run.
    """

    name = LOAD_SKILL_TOOL_NAME
    description = (
        "Load the full instructions for a skill listed in the Skills catalog. "
        "Call this when a task matches a catalog entry and you need its "
        "detailed guidance. Loading a skill may also unlock additional tools."
    )
    prompt_instructions = (
        "Load a skill only when the current task matches its summary. One call "
        "per skill; a loaded skill stays available for the rest of the run."
    )

    def __init__(
        self,
        lookup: Any,
        session: SkillSession,
        *,
        available_tools: Iterable[str] | None = None,
    ) -> None:
        """*lookup* maps an id to a skill, or ``None``. Accepts a Mapping or a callable."""
        self._lookup = lookup
        self._session = session
        self._available = None if available_tools is None else set(available_tools)

    # -- tool protocol -----------------------------------------------------

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {
                            "type": "string",
                            "description": "Id of the skill, exactly as listed in the catalog.",
                        }
                    },
                    "required": ["skill_id"],
                },
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        from shipit_agent.tools_compat import make_output  # tiny shim, see module docstring

        skill_id = str(kwargs.get("skill_id", "")).strip()
        if not skill_id:
            return make_output("No skill_id given. Pass an id from the catalog.")

        skill = self._resolve(skill_id)
        if skill is None:
            return make_output(self._not_found(skill_id))

        if self._session.is_primed(skill_id):
            return make_output(
                f"Skill '{skill_id}' is already loaded; its instructions are "
                "already in this conversation."
            )

        primed = self._session.prime(
            skill, trigger="model", available_tools=self._available
        )
        if primed is None:
            return make_output(
                f"Cannot load more skills this turn (limit "
                f"{self._session.caps.primed_per_turn}). Work with what is loaded."
            )

        unlocked = (
            f"\n\nTools now available: {', '.join(primed.tools)}."
            if primed.tools
            else ""
        )
        return make_output(
            f"# Skill loaded: {primed.name}\n\n{primed.body}{unlocked}",
            metadata={
                "skill_id": primed.id,
                "skill_trigger": primed.trigger,
                "unlocked_tools": list(primed.tools),
                "source": SKILL_MESSAGE_SOURCE,
            },
        )

    # -- internals ---------------------------------------------------------

    def _resolve(self, skill_id: str) -> SkillLike | None:
        if callable(self._lookup):
            return self._lookup(skill_id)
        if isinstance(self._lookup, Mapping):
            return self._lookup.get(skill_id)
        return None

    def _known_ids(self) -> Sequence[str]:
        if isinstance(self._lookup, Mapping):
            return sorted(self._lookup.keys())
        return ()

    def _not_found(self, skill_id: str) -> str:
        known = self._known_ids()
        needle = skill_id.lower()
        near = [k for k in known if needle in k.lower() or k.lower() in needle][:5]
        if near:
            return (
                f"No skill with id '{skill_id}'. Closest matches: "
                f"{', '.join(near)}."
            )
        return (
            f"No skill with id '{skill_id}'. Use an id exactly as written in "
            "the Skills catalog."
        )
