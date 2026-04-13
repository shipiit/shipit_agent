"""ShipTask — a single unit of work in a ShipCrew DAG workflow.

Tasks form a directed acyclic graph (DAG) via their ``depends_on``
field.  Template variables like ``{output_key}`` in the description
are resolved from upstream task outputs at execution time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Safe template resolution
# ---------------------------------------------------------------------------

class _SafeFormatMap(dict):
    """Dict subclass that returns ``{key}`` for missing keys.

    Prevents ``KeyError`` when a template variable hasn't been
    populated yet (e.g. during validation before execution).
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# ---------------------------------------------------------------------------
# ShipTask
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ShipTask:
    """A single task in a ShipCrew workflow.

    Tasks form a directed acyclic graph (DAG) via ``depends_on``.
    Template variables like ``{output_key}`` resolve from upstream
    task outputs at execution time.

    Example::

        research = ShipTask(
            name="research",
            description="Research {topic} thoroughly",
            agent="researcher",
            output_key="findings",
        )
        write = ShipTask(
            name="write",
            description="Write report using {findings}",
            agent="writer",
            depends_on=["research"],
            output_key="report",
        )
    """

    name: str
    description: str
    agent: str
    depends_on: list[str] = field(default_factory=list)
    output_key: str = ""
    output_schema: Any = None
    max_retries: int = 1
    timeout_seconds: int = 300
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Default output_key to the task name if not explicitly set.
        if not self.output_key:
            self.output_key = self.name

    # ------------------------------------------------------------------ #
    # Template resolution
    # ------------------------------------------------------------------ #

    def resolve_description(self, outputs: dict[str, str]) -> str:
        """Substitute ``{var}`` placeholders from upstream outputs.

        Uses a safe format map so that unresolved variables are left
        as-is rather than raising ``KeyError``.

        Args:
            outputs: Mapping of ``output_key`` -> result string from
                     completed upstream tasks.

        Returns:
            The description with all resolvable placeholders filled in.
        """
        return self.description.format_map(_SafeFormatMap(outputs))

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Convert the task to a plain dict for logging or persistence."""
        return {
            "name": self.name,
            "description": self.description,
            "agent": self.agent,
            "depends_on": list(self.depends_on),
            "output_key": self.output_key,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "context": dict(self.context),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShipTask:
        """Create a ``ShipTask`` from a plain dict.

        Unknown keys are silently ignored so that forward-compatible
        serialisation is possible.
        """
        return cls(
            name=data["name"],
            description=data["description"],
            agent=data["agent"],
            depends_on=list(data.get("depends_on", [])),
            output_key=data.get("output_key", data["name"]),
            output_schema=data.get("output_schema"),
            max_retries=data.get("max_retries", 1),
            timeout_seconds=data.get("timeout_seconds", 300),
            context=dict(data.get("context", {})),
        )
