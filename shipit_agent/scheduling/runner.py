"""ScheduleRunner: runs one scheduled agent and reports its result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

from shipit_agent.core.models import AgentEvent, AgentResult

from .config import ScheduledAgentConfig, ScheduleResult


@dataclass(slots=True)
class ScheduleRunner:
    """Execute an agent or session-backed agent call on behalf of a scheduler."""

    agent: Any = None
    agent_resolver: Callable[[ScheduledAgentConfig], Any] | None = None

    def execute(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
        job_name: str | None = None,
    ) -> ScheduleResult:
        selected = config or ScheduledAgentConfig()
        agent = self._resolve_agent(selected)
        if session_id is not None:
            result = self._chat_session(agent, session_id).send(prompt)
        else:
            result = agent.run(prompt)

        usage = self._usage(result)
        token_count = int(usage.get("total_tokens", 0) or 0)
        if token_count <= 0:
            token_count = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        if token_count <= 0:
            token_count = sum(
                int(value) for value in usage.values() if isinstance(value, int | float)
            )
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "job_name": job_name,
                "session_id": session_id,
                "token_count": token_count,
                "usage": usage,
                "agent_config": selected.to_dict(),
            },
        )

    def execute_stream(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
    ) -> Iterator[AgentEvent]:
        agent = self._resolve_agent(config or ScheduledAgentConfig())
        if session_id is not None:
            yield from self._chat_session(agent, session_id).stream(prompt)
            return
        yield from agent.stream(prompt)

    def execute_stream_result(
        self,
        prompt: str,
        session_id: str | None = None,
        *,
        config: ScheduledAgentConfig | None = None,
        job_name: str | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> ScheduleResult:
        """Consume a live run while preserving its events and final output."""
        selected = config or ScheduledAgentConfig()
        events: list[AgentEvent] = []
        for event in self.execute_stream(
            prompt,
            session_id=session_id,
            config=selected,
        ):
            events.append(event)
            if on_event is not None:
                try:
                    on_event(event)
                except Exception:
                    # Observability must not turn a successful agent run into
                    # a failed scheduled job.
                    pass

        completed = next(
            (event for event in reversed(events) if event.type == "run_completed"),
            None,
        )
        payload = completed.payload if completed is not None else {}
        usage = dict(payload.get("usage", {}))
        output = str(payload.get("output") or payload.get("content") or "")
        token_count = int(usage.get("total_tokens", 0) or 0)
        if token_count <= 0:
            token_count = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        result = AgentResult(
            output=output,
            messages=[],
            events=events,
            metadata={"usage": usage},
        )
        return ScheduleResult(
            agent_result=result,
            schedule_metadata={
                "job_name": job_name,
                "session_id": session_id,
                "token_count": token_count,
                "usage": usage,
                "agent_config": selected.to_dict(),
                "streamed": True,
            },
        )

    def _resolve_agent(self, config: ScheduledAgentConfig) -> Any:
        config.validate()
        if self.agent_resolver is not None:
            return self.agent_resolver(config)
        if self.agent is None:
            raise RuntimeError("scheduled job has no agent or agent_resolver")
        return self.agent

    @staticmethod
    def _usage(result: Any) -> dict[str, Any]:
        metadata_usage = getattr(result, "metadata", {}).get("usage", {})
        if isinstance(metadata_usage, dict) and metadata_usage:
            return dict(metadata_usage)
        for event in reversed(list(getattr(result, "events", []) or [])):
            if getattr(event, "type", "") != "run_completed":
                continue
            usage = getattr(event, "payload", {}).get("usage", {})
            if isinstance(usage, dict):
                return dict(usage)
        return {}

    @staticmethod
    def _chat_session(agent: Any, session_id: str) -> Any:
        try:
            return agent.chat_session(session_id=session_id)
        except TypeError:
            return agent.chat_session(session_id)

