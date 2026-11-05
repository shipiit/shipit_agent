"""The load_skill tool, and the note listing a loaded skill's bundled files."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .entries import LOAD_SKILL_TOOL_NAME, SKILL_MESSAGE_SOURCE, SkillLike
from .session import SkillSession


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
    # Capability loaders should be reachable without first discovering the
    # discovery mechanism. This is a preference within the configured budget,
    # not an exemption from permissions or a grant of the skill's tools.
    discovery_priority = 10
    read_only = True
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
        from shipit_agent.core.tools_compat import (
            make_output,  # tiny shim, see module docstring
        )

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
            f"# Skill loaded: {primed.name}\n\n{primed.body}{unlocked}"
            + _bundle_note(getattr(skill, "directory", "")),
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
            return f"No skill with id '{skill_id}'. Closest matches: {', '.join(near)}."
        return (
            f"No skill with id '{skill_id}'. Use an id exactly as written in "
            "the Skills catalog."
        )


#: Bundled files listed when a skill loads; the rest are counted.
_BUNDLE_LISTING_LIMIT = 30


def _bundle_note(directory: str) -> str:
    """Where a loaded skill lives and the files it bundles, for the model.

    Paths are relative to the base directory, so instructions like "run
    scripts/fill.py" can be followed from it.
    """
    if not directory:
        return ""
    from pathlib import Path

    base = Path(directory)
    if not base.is_dir():
        return ""
    files = sorted(
        str(path.relative_to(base))
        for path in base.rglob("*")
        if path.is_file()
        and path.name != "SKILL.md"
        and "__pycache__" not in path.parts
    )
    note = f"\n\nBase directory: {base}"
    if files:
        shown = files[:_BUNDLE_LISTING_LIMIT]
        more = len(files) - len(shown)
        note += "\nBundled files (relative to it): " + ", ".join(shown)
        if more:
            note += f", and {more} more"
    return note
