"""Two streams, not one — what a web client needs to render a live run.

A terminal renderer can hold state in memory: it knows what it drew and can
rewind it. A browser cannot. It disconnects, reloads, reconnects to a server
that may have restarted, and has to decide whether what it drew half a second
ago is still true.

Cloudflare OS solves this by separating two things a single event log conflates:

============  ==========================  ===========================
              **canonical**               **provisional**
============  ==========================  ===========================
what          the durable record          what it looks like right now
written       once per completed turn     continuously, as tokens arrive
lifetime      forever                     until the durable record lands
on reconnect  replayed                    **discarded**
============  ==========================  ===========================

and by sending a ``streamGeneration`` marker at the start of every
subscription — an opaque value identifying the server instance. A reconnecting
client that sees a *different* generation knows the server restarted, so any
half-drawn provisional state is garbage and the turn will re-stream from
scratch. An unchanged generation means a plain network blip: keep what you had.

This module is that vocabulary for shipit. It classifies each ``AgentEvent``
and frames it for SSE, so a browser can render the same transcript the terminal
does — and survive losing its connection halfway through.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from shipit_agent.models import AgentEvent

__all__ = [
    "Durability",
    "StreamFrame",
    "STREAM_GENERATION",
    "classify",
    "frame",
    "sse",
    "sse_stream",
    "hello_frame",
]


class Durability(str, Enum):
    """Whether a client should keep this after a reconnect."""

    CANONICAL = "canonical"  # replayed; part of the record
    PROVISIONAL = "provisional"  # discard on reconnect; it will re-stream
    CONTROL = "control"  # about the stream itself


# One value per process, stamped once at import. A restarted server gets a new
# one, which is exactly the signal a reconnecting client needs. Includes the
# pid so two workers behind a load balancer are distinguishable — a client
# bounced between them must treat that as a restart, because the second worker
# has none of the first's in-flight state.
STREAM_GENERATION = f"{os.getpid()}-{int(time.time() * 1000)}"


# Events that survive a reconnect because they describe what *happened*.
_CANONICAL = frozenset(
    {
        "run_started",
        "tool_called",
        "tool_completed",
        "tool_failed",
        "tool_denied",
        "tool_arguments_rejected",
        "action_queued",
        "sub_agent_event",
        "run_completed",
        "run_cancelled",
        "context_compacted",
        "guardrail_triggered",
        "lockdown_engaged",
        "rag_sources",
        "mcp_attached",
        "interactive_request",
        "planning_started",
        "planning_completed",
        "reasoning_completed",
        # The run's outcome and its public narration are the record, not an
        # in-flight moment — a reconnecting client that drops `final_answer`
        # has silently lost the answer itself.
        "final_answer",
        "run_summary",
        "agent_decision",
        "agent_observation",
        "tool_group_started",
        "tool_group_completed",
        "artifact_created",
        "skills_selected",
    }
)

# Events that describe an in-flight moment. A client that reconnects mid-turn
# has a half-written file on screen and no way to finish it; the only correct
# thing is to drop it and let the re-stream rebuild it.
_PROVISIONAL = frozenset(
    {
        "text_delta",
        "reasoning_started",
        "tool_input_started",
        "tool_input_delta",
        "tool_output_started",
        "tool_output_delta",
        "usage_tick",
        "step_started",
        "llm_retry",
        "tool_retry",
        "tool_call_healed",
    }
)


def classify(event_type: str) -> Durability:
    """How a client should treat this event across a reconnect."""
    if event_type in _CANONICAL:
        return Durability.CANONICAL
    if event_type in _PROVISIONAL:
        return Durability.PROVISIONAL
    # Unknown events are provisional: dropping something that turns out to
    # have been durable costs a redraw, keeping something that turns out to
    # have been in-flight leaves a lie on the screen.
    return Durability.PROVISIONAL


def _jsonable(value: Any) -> Any:
    """Coerce a payload into something ``json.dumps`` accepts.

    Payloads carry arbitrary tool arguments; one unserializable value must not
    be able to kill a stream mid-response.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass(slots=True)
class StreamFrame:
    """One event, framed for the wire."""

    type: str
    durability: Durability
    payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    generation: str = STREAM_GENERATION
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "durability": self.durability.value,
            "generation": self.generation,
            "sequence": self.sequence,
            "message": self.message,
            "payload": _jsonable(self.payload),
            "timestamp": self.timestamp,
        }


def frame(event: AgentEvent, *, sequence: int = 0) -> StreamFrame:
    """Classify and frame one agent event."""
    return StreamFrame(
        type=event.type,
        durability=classify(event.type),
        payload=dict(event.payload),
        message=event.message,
        timestamp=event.timestamp,
        sequence=sequence,
    )


def hello_frame() -> StreamFrame:
    """The first frame of any subscription.

    Sent before anything else so a reconnecting client can compare generations
    *before* it decides what to do with the state it already has.
    """
    return StreamFrame(
        type="stream_hello",
        durability=Durability.CONTROL,
        message="Stream opened",
        payload={
            "generation": STREAM_GENERATION,
            "discard_provisional": True,
        },
    )


# ── SSE framing ──────────────────────────────────────────────────────────


def sse(frame_or_event: StreamFrame | AgentEvent, *, sequence: int = 0) -> str:
    """One Server-Sent Event.

    Named by type so a browser can use ``addEventListener('tool_called', …)``
    instead of parsing every message, and given an ``id:`` so the browser's
    own ``Last-Event-ID`` reconnect machinery works without extra code.
    """
    rendered = (
        frame_or_event
        if isinstance(frame_or_event, StreamFrame)
        else frame(frame_or_event, sequence=sequence)
    )
    body = json.dumps(rendered.to_dict())
    return f"id: {rendered.sequence}\nevent: {rendered.type}\ndata: {body}\n\n"


def sse_stream(events: Iterable[AgentEvent]) -> Iterable[str]:
    """Frame a whole run, hello first, with a terminating sentinel."""
    yield sse(hello_frame())
    sequence = 0
    for event in events:
        sequence += 1
        yield sse(event, sequence=sequence)
    yield "event: done\ndata: [DONE]\n\n"


def replay_from(
    events: Iterable[AgentEvent], last_sequence: int
) -> Iterable[AgentEvent]:
    """Events a reconnecting client missed.

    Only canonical ones: provisional events describe a moment that has passed,
    and replaying a half-written file would put back exactly the state the
    client was told to discard.
    """
    for index, event in enumerate(events, start=1):
        if index > last_sequence and classify(event.type) is Durability.CANONICAL:
            yield event
