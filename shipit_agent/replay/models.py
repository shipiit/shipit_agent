"""Dataclasses for the time-travel replay system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.models import AgentEvent, Message


@dataclass(slots=True)
class ForkPoint:
    """Describes how a trace was forked.

    Recorded on every replay so you can later see "this run is a fork of
    that one at event N with these edits applied".
    """

    source_trace_id: str
    """The ID of the original trace we forked from."""

    at_event: int
    """The 0-indexed event number we forked at."""

    edits: dict[str, Any] = field(default_factory=dict)
    """Map of {edit_kind: details} — e.g. {"user_message": "new text"}.
    Empty dict means "fork at this event with no edits"."""


@dataclass(slots=True)
class ReplayCheckpoint:
    """State captured at a fork point — enough to resume an agent run.

    Carries the messages reconstructed from the trace up to (and including)
    ``at_event``, along with the optional edits the caller wants applied
    when resuming.
    """

    fork: ForkPoint
    """How we got here."""

    messages: list[Message]
    """Reconstructed conversation history. Replace the last user message
    if ``fork.edits.get('user_message')`` is set."""

    user_prompt: str
    """The prompt to feed into ``agent.run(prompt=...)`` when resuming.
    Either the original last user message OR the edited replacement."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Carry-over metadata from the source trace (model, agent name, etc.)."""

    def continue_from(self, *, agent: Any, **run_kwargs: Any) -> "ReplayResult":
        """Run the supplied agent starting from this checkpoint.

        Pre-fills ``agent.history`` with the reconstructed messages, then
        calls ``agent.run(self.user_prompt, **run_kwargs)``. Returns a
        ``ReplayResult`` bundling the agent's result with replay metadata.
        """
        # Some agents accept history via constructor only; we mutate the
        # public list to keep the API tiny.
        if hasattr(agent, "history"):
            agent.history = list(self.messages)
        result = agent.run(self.user_prompt, **run_kwargs)
        return ReplayResult(
            agent_result=result,
            fork=self.fork,
            checkpoint_messages=list(self.messages),
        )


@dataclass(slots=True)
class ReplayResult:
    """The outcome of resuming a fork — wraps an ``AgentResult``."""

    agent_result: Any
    """The ``AgentResult`` returned by ``agent.run()``."""

    fork: ForkPoint
    """How this run forked from the source trace."""

    checkpoint_messages: list[Message]
    """The messages we resumed from (snapshot of the fork point)."""

    @property
    def output(self) -> str:
        return getattr(self.agent_result, "output", "")

    @property
    def events(self) -> list[AgentEvent]:
        return getattr(self.agent_result, "events", [])

    @property
    def messages(self) -> list[Message]:
        return getattr(self.agent_result, "messages", [])
