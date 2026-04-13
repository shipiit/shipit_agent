"""Core data structures and protocol for the notification subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


# Severity levels ordered from lowest to highest.
SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}


@dataclass(slots=True)
class Notification:
    """A single notification to be sent to one or more channels.

    Attributes:
        event:    Lifecycle event name, e.g. ``"run_started"``,
                  ``"run_completed"``, ``"tool_failed"``, ``"cost_alert"``,
                  ``"checkpoint_saved"``.
        title:    Short human-readable title for the notification.
        message:  Detailed message body with context.
        severity: One of ``"info"``, ``"warning"``, ``"error"``,
                  ``"critical"``.  Defaults to ``"info"``.
        metadata: Arbitrary key/value pairs — agent name, duration, cost,
                  tool name, etc.
        timestamp: UTC timestamp when the notification was created.
    """

    event: str
    title: str
    message: str
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "event": self.event,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp.isoformat(),
        }


@runtime_checkable
class Notifier(Protocol):
    """Protocol that every notification channel must implement.

    Channels only need to provide :meth:`send`.  The default
    :meth:`send_batch` fans out to :meth:`send` sequentially, but
    implementations may override it for efficiency.
    """

    name: str

    async def send(self, notification: Notification) -> bool:
        """Send a single notification.  Returns ``True`` on success."""
        ...

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
        """Send multiple notifications.  Returns a list of success flags."""
        ...
