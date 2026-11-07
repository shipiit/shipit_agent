"""The accumulator: events in, transcript rows out, for the live view and replays."""

from __future__ import annotations

from typing import Any, Iterable

from shipit_agent.core.models import AgentEvent

from .calls import CallRecord, WorkGroup, build_group
from .card_events import CardEventsMixin
from .rows import ArtifactRow, ProseRow, SubAgentRow, TranscriptRow, WorkRow
from .tool_events import ToolEventsMixin

#: Event type → the handler that takes it in. Anything else may be a notice.
_HANDLERS = {
    "text_delta": "_on_text_delta",
    "tool_called": "_on_tool_called",
    "tool_completed": "_on_tool_completed",
    "tool_failed": "_on_tool_failed",
    "tool_denied": "_on_tool_denied",
    "tool_input_started": "_on_tool_input_started",
    "tool_input_delta": "_on_tool_input_delta",
    "sub_agent_event": "_on_sub_agent_event",
    "action_queued": "_on_action_queued",
    "agent_decision": "_on_agent_decision",
    "agent_observation": "_on_agent_observation",
    "artifact_created": "_on_artifact_created",
    "connection_requested": "_on_connection_requested",
    "tool_group_completed": "_on_tool_group_completed",
    "usage_tick": "_on_usage_tick",
    "run_completed": "_on_run_completed",
}


class WorkRunAccumulator(ToolEventsMixin, CardEventsMixin):
    """Feed events in, get transcript rows out — the live and offline core.

    Buffers tool calls until prose (or the end of the run) breaks the run,
    then emits the collapsed :class:`WorkRow`. Everything the renderer and
    :func:`build_transcript` need to agree on lives here, so the live view
    and the replayed transcript can never drift.
    """

    def __init__(self) -> None:
        self._calls: list[CallRecord] = []
        self._by_id: dict[str, CallRecord] = {}
        self._prose: list[str] = []
        self._rows: list[TranscriptRow] = []
        # The runtime's own grouping, when it emits one. With progress
        # narration on, prose lands between every call — and the old rule
        # ("prose breaks a run") would then put every single call in a row of
        # its own. A declared group is authoritative: it says which calls
        # belong together regardless of what was said between them.
        self._group_id: str | None = None
        # Cards for files made inside the group currently open, drawn once it
        # closes so they sit under the row that made them.
        self._pending_artifacts: list[ArtifactRow] = []
        self.usage: dict[str, int] = {}
        # The tool argument currently being written, keyed by call id, so a
        # live view can show a file appearing rather than nothing until the
        # call completes.
        self.writing: dict[str, str] = {}
        # Work done by delegated agents, keyed by (agent, task).
        self._sub_agents: dict[tuple[str, str], SubAgentRow] = {}
        # A background child can outlive the parent work that started it.
        # Its row is held, not settled, until the child's run ends, so a view
        # that prints settled rows once still shows the child's whole work.
        self._held_sub_agents: dict[tuple[str, str], SubAgentRow] = {}
        self._finished_sub_agents: set[tuple[str, str]] = set()
        # Rows already settled, in case a child reports after its run ended.
        self._emitted_sub_agents: dict[tuple[str, str], SubAgentRow] = {}

    # ── ingest ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> list[TranscriptRow]:
        """Consume one event; return rows that became final because of it."""
        before = len(self._rows)
        handler = _HANDLERS.get(event.type)
        if handler is not None:
            getattr(self, handler)(event)
        else:
            self._on_notice(event.type, event.payload)
        return self._rows[before:]

    def _on_text_delta(self, event: AgentEvent) -> None:
        chunk = str(event.payload.get("chunk", ""))
        if chunk:
            # Prose breaks a work run — unless the runtime declared the
            # group, in which case the group decides where it ends.
            if self._group_id is None:
                self._flush_work()
            self._prose.append(chunk)

    def _on_tool_group_completed(self, event: AgentEvent) -> None:
        # The runtime says this batch is done; anything after it belongs
        # to the next row.
        self._flush_work()
        self._group_id = None

    def _on_usage_tick(self, event: AgentEvent) -> None:
        self.usage = dict(event.payload.get("usage") or {})

    # ── flush ────────────────────────────────────────────────────────────

    def _flush_work(self) -> None:
        group = build_group(self._calls)
        if group is not None:
            self._rows.append(WorkRow(group))
        # Whatever that work produced belongs directly under it.
        self._rows.extend(self._pending_artifacts)
        self._pending_artifacts = []
        # A child's work belongs under the delegation that started it; one
        # still running is held until it finishes.
        for key, row in self._sub_agents.items():
            if key in self._finished_sub_agents:
                self._settle_sub_agent(key, row)
            else:
                self._held_sub_agents[key] = row
        self._sub_agents = {}
        self._calls = []
        self._by_id = {}

    def _flush_prose(self) -> None:
        text = "".join(self._prose).strip()
        self._prose = []
        if text:
            self._rows.append(ProseRow(text))

    # ── views ────────────────────────────────────────────────────────────

    @property
    def writing_preview(self) -> str:
        """The tail of whatever argument is being written right now."""
        for value in reversed(list(self.writing.values())):
            if value:
                return value
        return ""

    @property
    def pending(self) -> WorkGroup | None:
        """The in-flight work run, in the present tense — for the live row."""
        return build_group(self._calls, present=True)

    @property
    def streaming_text(self) -> str:
        """Prose that has arrived but is not yet a settled row.

        A live view needs the half-written sentence; a transcript never does.
        Exposed so a renderer can show tokens landing without reaching into
        the buffer this class flushes.
        """
        return "".join(self._prose)

    def live_rows(self) -> list[TranscriptRow]:
        """Settled rows *plus* whatever is still in flight.

        The same list :attr:`rows` returns, with the in-flight work run and
        the half-written sentence appended in the order they will settle in.
        Calling this never commits anything — feed the next event and the
        provisional tail is recomputed from scratch.
        """
        rows: list[TranscriptRow] = list(self._rows)
        pending = self.pending
        if pending is not None:
            rows.append(WorkRow(pending))
        rows.extend(self._held_sub_agents.values())
        rows.extend(self._sub_agents.values())
        text = self.streaming_text
        if text.strip():
            rows.append(ProseRow(text))
        return rows

    def _settle_sub_agent(self, key: tuple[str, str], row: SubAgentRow) -> None:
        self._rows.append(row)
        self._emitted_sub_agents[key] = row

    def finish(self) -> list[TranscriptRow]:
        """Close out anything still buffered and return the new rows."""
        before = len(self._rows)
        self._flush_work()
        for key, row in self._held_sub_agents.items():
            self._settle_sub_agent(key, row)
        self._held_sub_agents = {}
        self._flush_prose()
        return self._rows[before:]

    @property
    def rows(self) -> list[TranscriptRow]:
        return list(self._rows)


def build_transcript(source: Iterable[AgentEvent] | Any) -> list[TranscriptRow]:
    """A finished run's events → ordered transcript rows.

    Accepts an ``AgentResult`` or any iterable of events.
    """
    events = getattr(source, "events", source)
    accumulator = WorkRunAccumulator()
    for event in events:
        accumulator.feed(event)
    accumulator.finish()
    return accumulator.rows
