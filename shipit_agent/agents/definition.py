"""AgentDefinition dataclass — describes a prebuilt agent's identity, prompt, and metadata."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field, fields
from typing import Any


# ---------------------------------------------------------------------------
# Case-conversion helpers (mirrors shipit_agent.skills.skill)
# ---------------------------------------------------------------------------

def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ---------------------------------------------------------------------------
# AgentDefinition
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AgentDefinition:
    """A prebuilt agent definition with identity, behaviour prompt, and metadata.

    An ``AgentDefinition`` is a *template* — it describes what an agent
    should be, but does not hold runtime state.  The ``AgentRegistry``
    loads collections of these from JSON and hands them to the framework
    when a user selects a prebuilt agent.
    """

    # --- identity ---
    id: str = ""
    name: str = ""
    role: str = ""
    goal: str = ""
    backstory: str = ""

    # --- execution ---
    model: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    max_iterations: int = 8
    prompt: str = ""

    # --- metadata ---
    category: str = ""
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    author: str = "shipit"

    # --------------------------------------------------------------------- #
    # Serialisation
    # --------------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict with camelCase keys (matching the JSON wire format)."""
        result: dict[str, Any] = {}
        for f in fields(self):
            key = _snake_to_camel(f.name)
            value = getattr(self, f.name)
            # Defensive copy for mutable containers
            if isinstance(value, list):
                value = list(value)
            result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDefinition:
        """Create an AgentDefinition from a dict with either snake_case or camelCase keys."""
        valid_names = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}

        for key, value in data.items():
            snake = _camel_to_snake(key)
            if snake in valid_names:
                kwargs[snake] = value
            elif key in valid_names:
                kwargs[key] = value

        return cls(**kwargs)

    # --------------------------------------------------------------------- #
    # Prompt construction
    # --------------------------------------------------------------------- #

    def system_prompt(self) -> str:
        """Build the full system prompt by combining role, goal, backstory, and prompt.

        The assembled prompt gives the LLM a clear identity before diving
        into task-specific instructions.
        """
        sections: list[str] = []

        if self.role:
            sections.append(f"# Role\nYou are a {self.role}.")

        if self.goal:
            sections.append(f"# Goal\n{self.goal}")

        if self.backstory:
            sections.append(f"# Background\n{self.backstory}")

        if self.prompt:
            sections.append(
                f"# Instructions\n{textwrap.dedent(self.prompt).strip()}"
            )

        return "\n\n".join(sections)
