"""AutopilotResult — the final envelope returned by run() / resume()."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AutopilotResult:
    """Final envelope returned by :meth:`Autopilot.run` and :meth:`Autopilot.resume`.

    ``status`` values:
      - ``completed`` — every criterion passed before budgets tripped.
      - ``partial``   — some criteria passed; budget tripped or halted.
      - ``halted``    — budget tripped before any criterion was verified.
      - ``failed``    — an unhandled exception aborted the run.
    """

    run_id: str
    status: str = "unknown"
    goal: dict[str, Any] = field(default_factory=dict)
    criteria_met: list[bool] = field(default_factory=list)
    iterations: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    halt_reason: str = ""
    step_outputs: list[dict[str, Any]] = field(default_factory=list)
    # Artifacts (code blocks, markdown docs, tool-declared deliverables)
    # collected during the run. Empty unless an ArtifactCollector was wired
    # into the Autopilot — the list preserves chronological order.
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    # Last critic verdict, when a critic was enabled. Always present as a
    # dict — an empty dict means "no critic ran this iteration".
    critic_verdict: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
