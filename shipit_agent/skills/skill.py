"""Skill dataclass representing a single agent skill/capability."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


@dataclass
class Skill:
    """A single agent skill with metadata, configuration, and marketplace info."""

    # --- identity ---
    id: str = ""
    name: str = ""
    display_name: str = ""
    description: str = ""
    detailed_description: str = ""
    long_description: str = ""
    version: str = "1.0.0"
    author: str = ""
    category: str = ""

    # --- discovery ---
    tags: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    how_to_use: list[str] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)

    # --- examples ---
    sample_output: str = ""
    before_after: dict = field(default_factory=dict)

    # --- pricing / marketplace ---
    pricing: str = "free"
    price: float = 0.0
    credit_cost: float = 0.0
    tier: str = "free"

    # --- visibility / status ---
    is_visible: bool = True
    is_admin_enabled: bool = True
    is_user_enabled: bool = True
    featured: bool = False
    premium: bool = False

    # --- social / ratings ---
    like_count: int = 0
    avg_rating: float = 0.0
    review_count: int = 0
    total_sales: int = 0

    # --- execution ---
    tools: list[str] = field(default_factory=list)
    prompt_template: str = ""
    mcps: list[dict] = field(default_factory=list)
    input_type: str = ""
    output_type: str = ""
    requirements: list[str] = field(default_factory=list)

    # --- ownership ---
    creator_id: str = ""

    # --------------------------------------------------------------------- #
    # Serialisation helpers
    # --------------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict with camelCase keys (matching the JSON wire format)."""
        result: dict[str, Any] = {}
        for f in fields(self):
            key = _snake_to_camel(f.name)
            value = getattr(self, f.name)
            # copy mutable containers so callers can't accidentally mutate us
            if isinstance(value, (list, dict)):
                value = value.copy() if isinstance(value, dict) else list(value)
            result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        """Create a Skill from a dict that may use either snake_case or camelCase keys."""
        valid_names = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}

        for key, value in data.items():
            snake = _camel_to_snake(key)
            if snake in valid_names:
                kwargs[snake] = value
            elif key in valid_names:
                kwargs[key] = value

        return cls(**kwargs)

    def prompt_text(self) -> str:
        """Return the prompt block that should be applied for this skill.

        Marketplace records often contain metadata but no explicit
        ``prompt_template``. In that case we derive a compact instruction
        block from the skill metadata so the runtime can still use it.
        """
        if self.prompt_template.strip():
            return self.prompt_template.strip()

        lines = [
            f"Skill: {self.display_name or self.name or self.id}",
        ]
        if self.description:
            lines.append(self.description.strip())
        if self.detailed_description:
            lines.append(self.detailed_description.strip())
        if self.use_cases:
            lines.append(
                "Use cases: " + "; ".join(case.strip() for case in self.use_cases[:5])
            )
        if self.how_to_use:
            lines.append(
                "Suggested workflow: "
                + "; ".join(step.strip() for step in self.how_to_use[:4])
            )
        if self.features:
            lines.append(
                "Key capabilities: "
                + "; ".join(feature.strip() for feature in self.features[:6])
            )
        if self.tools:
            lines.append("Prefer these tools when useful: " + ", ".join(self.tools))
        if self.requirements:
            lines.append(
                "Requirements/constraints: "
                + "; ".join(req.strip() for req in self.requirements[:5])
            )
        lines.append(
            "Apply this skill when the user's request matches its intent. "
            "Adapt the response to the current task instead of reciting the catalog."
        )
        return "\n\n".join(line for line in lines if line)
