"""Doctor check results and their status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CheckStatus = str


@dataclass(slots=True)
class DoctorCheck:
    """The outcome of one health check: its name, status and a message."""
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

