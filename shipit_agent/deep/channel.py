from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentMessage:
    """Typed message for agent-to-agent communication."""

    from_agent: str
    to_agent: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    requires_ack: bool = False
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "type": self.type,
            "data": self.data,
            "requires_ack": self.requires_ack,
            "acknowledged": self.acknowledged,
        }


class Channel:
    """Typed communication channel between agents.

    Example::

        channel = Channel(name="pipeline")
        channel.send(AgentMessage(
            from_agent="researcher",
            to_agent="writer",
            type="research_complete",
            data={"findings": [...]},
        ))
        msg = channel.receive(agent="writer")
        channel.ack(msg)
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._queues: dict[str, queue.Queue[AgentMessage]] = {}
        self._history: list[AgentMessage] = []

    def send(self, message: AgentMessage) -> None:
        """Send a message to the target agent's queue."""
        target = message.to_agent
        if target not in self._queues:
            self._queues[target] = queue.Queue()
        self._queues[target].put(message)
        self._history.append(message)

    def receive(
        self, *, agent: str, timeout: float | None = None
    ) -> AgentMessage | None:
        """Receive the next message for an agent."""
        if agent not in self._queues:
            self._queues[agent] = queue.Queue()
        try:
            return self._queues[agent].get(timeout=timeout)
        except queue.Empty:
            return None

    def ack(self, message: AgentMessage) -> None:
        """Acknowledge receipt of a message."""
        message.acknowledged = True

    def history(self) -> list[AgentMessage]:
        """Return all messages sent through this channel."""
        return list(self._history)

    def pending(self, *, agent: str) -> int:
        """Count pending messages for an agent."""
        q = self._queues.get(agent)
        return q.qsize() if q else 0
