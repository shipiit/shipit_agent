"""``TraceReplayer`` — load, inspect, and fork saved agent traces."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shipit_agent.models import AgentEvent, Message
from shipit_agent.tracing import TraceRecord

from .models import ForkPoint, ReplayCheckpoint


class TraceReplayer:
    """Wraps a ``TraceRecord`` to enable inspection + forked replay.

    Construct via:
    - ``TraceReplayer.from_record(record)`` — already-loaded record
    - ``TraceReplayer.from_store(store, trace_id)`` — pull from a TraceStore
    - ``TraceReplayer.from_file(path)`` — load JSON file directly
    """

    def __init__(self, record: TraceRecord) -> None:
        self.record = record

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    @classmethod
    def from_record(cls, record: TraceRecord) -> "TraceReplayer":
        return cls(record)

    @classmethod
    def from_store(cls, store: Any, trace_id: str) -> "TraceReplayer":
        record = store.load(trace_id)
        if record is None:
            raise FileNotFoundError(f"trace {trace_id!r} not found in store")
        return cls(record)

    @classmethod
    def from_file(cls, path: str | Path) -> "TraceReplayer":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"no trace file at {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TraceRecord(
            trace_id=raw.get("trace_id", path.stem),
            metadata=dict(raw.get("metadata", {})),
            events=[AgentEvent(**ev) for ev in raw.get("events", [])],
        )
        return cls(record)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    @property
    def trace_id(self) -> str:
        return self.record.trace_id

    @property
    def events(self) -> list[AgentEvent]:
        return list(self.record.events)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.record.metadata)

    def __len__(self) -> int:
        return len(self.record.events)

    def event_indices_by_type(self, event_type: str) -> list[int]:
        """Return the indices of all events with the given ``type``."""
        return [
            i for i, ev in enumerate(self.record.events) if ev.type == event_type
        ]

    def messages_at(self, event_index: int) -> list[Message]:
        """Reconstruct the conversation history as it existed *just after*
        ``event_index``.

        Walks the event log from the start, accumulating messages from
        ``run_started``, ``step_started``, ``tool_called``, and
        ``tool_completed`` payloads. Tolerates events that don't carry
        message data; only events with a ``message`` payload field
        contribute.
        """
        if event_index < 0 or event_index >= len(self.record.events):
            raise IndexError(
                f"event_index {event_index} out of range "
                f"(have {len(self.record.events)} events)"
            )
        messages: list[Message] = []
        for i in range(event_index + 1):
            ev = self.record.events[i]
            for msg in _extract_messages_from_event(ev):
                messages.append(msg)
        return messages

    def find_user_messages(self) -> list[tuple[int, str]]:
        """Return ``[(event_index, user_text), ...]`` for every user message."""
        out: list[tuple[int, str]] = []
        for i, ev in enumerate(self.record.events):
            for msg in _extract_messages_from_event(ev):
                if msg.role == "user":
                    out.append((i, msg.content))
        return out

    # ------------------------------------------------------------------
    # Fork + resume
    # ------------------------------------------------------------------
    def fork(
        self,
        *,
        at_event: int,
        edit_user_message: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> ReplayCheckpoint:
        """Produce a ``ReplayCheckpoint`` capturing state up to ``at_event``.

        Args:
            at_event: 0-indexed event number to fork at.
            edit_user_message: when set, replaces the *last* user message
                in the checkpoint (so resuming feels like "I would have asked
                this differently"). When None, the original user prompt is
                used and the agent will simply continue from where it was.
            extra_metadata: optional dict merged into the checkpoint metadata.

        Returns:
            ``ReplayCheckpoint`` ready to feed into an agent via
            ``checkpoint.continue_from(agent=...)``.
        """
        if at_event < 0 or at_event >= len(self.record.events):
            raise IndexError(
                f"at_event {at_event} out of range (have {len(self.record.events)} events)"
            )

        history = self.messages_at(at_event)
        user_prompt = self._extract_resume_prompt(history, edit_user_message)
        # Keep history without the trailing user message we're "re-asking";
        # the agent.run() call appends it itself.
        if edit_user_message is not None:
            history = _drop_trailing_user(history)

        edits: dict[str, Any] = {}
        if edit_user_message is not None:
            edits["user_message"] = edit_user_message

        metadata = {**self.record.metadata, **(extra_metadata or {})}

        return ReplayCheckpoint(
            fork=ForkPoint(
                source_trace_id=self.record.trace_id,
                at_event=at_event,
                edits=edits,
            ),
            messages=history,
            user_prompt=user_prompt,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the underlying record (round-trips with ``from_file``)."""
        return {
            "trace_id": self.record.trace_id,
            "metadata": dict(self.record.metadata),
            "events": [asdict(ev) for ev in self.record.events],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _extract_resume_prompt(
        self, history: list[Message], edit: str | None
    ) -> str:
        if edit is not None:
            return edit
        # Find the most recent user message in history, fall back to ""
        for msg in reversed(history):
            if msg.role == "user":
                return msg.content
        return ""


def _extract_messages_from_event(event: AgentEvent) -> list[Message]:
    """Pull any messages embedded in an event's payload.

    Tolerant of multiple schemas — looks at common payload keys
    (``messages``, ``message``, ``user_prompt``, ``tool_result``)
    and returns whatever it can reconstruct.
    """
    out: list[Message] = []
    payload = event.payload or {}

    # explicit messages list
    raw_messages = payload.get("messages")
    if isinstance(raw_messages, list):
        for raw in raw_messages:
            msg = _msg_from_dict(raw)
            if msg is not None:
                out.append(msg)

    # single message field
    raw_msg = payload.get("message")
    if isinstance(raw_msg, dict):
        msg = _msg_from_dict(raw_msg)
        if msg is not None:
            out.append(msg)

    # ``user_prompt`` shorthand
    raw_prompt = payload.get("user_prompt")
    if isinstance(raw_prompt, str) and raw_prompt:
        out.append(Message(role="user", content=raw_prompt))

    # ``tool_result`` payload — surface as an assistant turn
    if event.type == "tool_completed":
        text = payload.get("text") or payload.get("output")
        if isinstance(text, str):
            out.append(Message(role="assistant", content=text))

    # ``run_completed`` final answer
    if event.type == "run_completed":
        text = payload.get("output")
        if isinstance(text, str):
            out.append(Message(role="assistant", content=text))

    return out


def _msg_from_dict(raw: Any) -> Message | None:
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    content = raw.get("content")
    if not isinstance(role, str) or not isinstance(content, str):
        return None
    return Message(
        role=role,
        content=content,
        name=raw.get("name") if isinstance(raw.get("name"), str) else None,
        metadata=dict(raw.get("metadata") or {}),
    )


def _drop_trailing_user(messages: list[Message]) -> list[Message]:
    """Strip the most recent user message — used when forking with an edited prompt."""
    out = list(messages)
    while out and out[-1].role == "user":
        out.pop()
    return out
