"""ShipCrewResult — the output of a completed ShipCrew execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ShipCrewResult:
    """Result of a ShipCrew execution.

    Captures the final synthesized output, per-task results keyed by
    their ``output_key``, the actual execution order, and metadata
    such as timing and failure information.

    Example::

        result = crew.run(topic="AI agents")
        print(result.output)               # final combined text
        print(result.task_results["findings"])  # specific task output
        print(result.execution_order)       # ["research", "write"]
    """

    output: str
    task_results: dict[str, str] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    total_tasks: int = 0
    failed_tasks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the result to a plain dict."""
        return {
            "output": self.output,
            "task_results": dict(self.task_results),
            "execution_order": list(self.execution_order),
            "total_tasks": self.total_tasks,
            "failed_tasks": list(self.failed_tasks),
            "metadata": dict(self.metadata),
        }
