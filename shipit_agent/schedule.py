from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from .models import AgentEvent


@dataclass(slots=True)
class ScheduleResult:
    """Result envelope for a scheduled agent execution."""

    agent_result: Any
    schedule_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleRunner:
    """Execute an agent or session-backed agent call on behalf of a scheduler."""

    agent: Any

    def execute(self, prompt: str, session_id: str | None = None) -> ScheduleResult:
        if session_id is not None:
            result = self._chat_session(session_id).send(prompt)
        else:
            result = self.agent.run(prompt)

        usage = getattr(result, "metadata", {}).get("usage", {})
        token_count = sum(usage.values()) if isinstance(usage, dict) else 0
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "session_id": session_id,
                "token_count": token_count,
            },
        )

    def execute_stream(
        self,
        prompt: str,
        session_id: str | None = None,
    ) -> Iterator[AgentEvent]:
        if session_id is not None:
            yield from self._chat_session(session_id).stream(prompt)
            return
        yield from self.agent.stream(prompt)

    def _chat_session(self, session_id: str) -> Any:
        try:
            return self.agent.chat_session(session_id=session_id)
        except TypeError:
            return self.agent.chat_session(session_id)
