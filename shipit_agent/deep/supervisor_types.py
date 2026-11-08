"""Names Supervisor and its streaming run share."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Delegation:
    """Record of a single delegation."""

    round: int
    worker: str
    task: str
    output: str
    approved: bool = False

