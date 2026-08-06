"""Work runs — collapse a burst of tool calls into one readable row.

The rule that makes a transcript calm:

    Consecutive tool calls with no prose between them are ONE row.
    Prose breaks the run.

So a turn that reads three files, makes two edits and then explains itself
renders as two rows, not six::

    ▤ Read 3 files, made 2 edits                              ›
      app.py · models.py · views.py · urls.py

    I've split the view out and pointed the router at it.

Public surface:

- :func:`build_transcript` — a finished run's events → ordered rows
- :class:`WorkRunAccumulator` — the same logic, fed live, one event at a time
- :class:`WorkGroup` — one collapsed row, ready to render
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from shipit_agent.models import AgentEvent

from .verbs import (
    SEARCH,
    TOOL,
    describe_count,
    describe_count_present,
    icon_for,
    is_read_only,
    summarize,
)

__all__ = [
    "CallRecord",
    "WorkGroup",
    "ProseRow",
    "WorkRow",
    "ApprovalRow",
    "ArtifactRow",
    "ConnectionRow",
    "DecisionRow",
    "SubAgentRow",
    "NoticeRow",
    "TranscriptRow",
    "WorkRunAccumulator",
    "build_transcript",
    "build_group",
]

CallStatus = Literal["running", "ok", "error", "denied"]

# Beyond this many distinct tools in one run, naming them all is noise.
_MAX_NAMED_TOOLS = 3


def _lower_first(text: str) -> str:
    """``"Made 2 edits"`` → ``"made 2 edits"`` — for every part after the first.

    This one transform is what makes a composite label read as a sentence
    (``Read 3 files, made 2 edits``) rather than a list of headings.
    """
    return text[0].lower() + text[1:] if text else text


@dataclass(slots=True)
class CallRecord:
    """One tool call, from ``tool_called`` through to its outcome."""

    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    status: CallStatus = "running"
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    iteration: Any = None

    @property
    def read_only(self) -> bool:
        return is_read_only(self.name)

    @property
    def target(self) -> str | None:
        return summarize(self.name, self.arguments).target

    @property
    def shape(self) -> tuple[str, str]:
        """What this call reads as — the tool *and* its composed verb.

        Two calls to one tool can be different actions: `sub_agent` starting
        work and `sub_agent` collecting results share a name but not a verb.
        Grouping on the name alone renders "Delegated 3 tasks" for two
        delegations and a collection.
        """
        return (self.name, summarize(self.name, self.arguments).past)

    def past_label(self) -> str:
        return summarize(self.name, self.arguments).past_label()

    def present_label(self) -> str:
        return summarize(self.name, self.arguments).present_label()


@dataclass(slots=True)
class WorkGroup:
    """A run of tool calls, collapsed into one row.

    ``key`` is the first call's id — deliberately, so a row that the user
    expanded while it was still streaming stays expanded once it commits.
    """

    key: str
    icon: str
    label: str
    detail_lines: list[str]
    calls: list[CallRecord]
    running: bool = False

    @property
    def has_error(self) -> bool:
        return any(call.status in ("error", "denied") for call in self.calls)

    @property
    def duration_ms(self) -> float:
        return sum(call.duration_ms for call in self.calls)

    @property
    def read_only(self) -> bool:
        """True when every call in the run was an observation."""
        return bool(self.calls) and all(call.read_only for call in self.calls)


def _detail_lines(calls: list[CallRecord]) -> list[str]:
    """Deduplicated targets, in first-seen order."""
    seen: set[str] = set()
    lines: list[str] = []
    for call in calls:
        target = call.target
        if target and target not in seen:
            seen.add(target)
            lines.append(target)
    return lines


def _compose_label(calls: list[CallRecord], *, present: bool) -> str:
    """The one-line summary for a run of calls.

    Ported from Cloudflare OS's ``buildToolCallGroups``, with one adaptation:
    when a run has more distinct tools than we'll name and *every* call was
    read-only, it reads ``5 resource reads`` rather than ``5 tool calls`` —
    the same phrasing their gatekeeper observations get, applied to the case
    where it's actually true for us.
    """
    describe = describe_count_present if present else describe_count
    # Group on the *shape* — tool plus composed verb — so two calls to one
    # tool that read as different actions are counted separately.
    shapes: list[tuple[str, str]] = []
    for call in calls:
        if call.shape not in shapes:
            shapes.append(call.shape)
    details = _detail_lines(calls)

    if len(calls) == 1:
        call = calls[0]
        return call.present_label() if present else call.past_label()

    if len(shapes) == 1:
        # A repeated tool that kept hitting the same target reads better as
        # the plain verb ("Edited app.py") than as a count ("Made 3 edits").
        if len(details) == 1:
            call = calls[0]
            return call.present_label() if present else call.past_label()
        return describe(shapes[0][0], len(calls))

    if len(shapes) <= _MAX_NAMED_TOOLS:
        parts: list[str] = []
        for shape in shapes:
            matching = [c for c in calls if c.shape == shape]
            if len(matching) == 1:
                # A lone call inside a mixed run keeps its target. Without it,
                # verbs that end in a preposition dangle: "searched for" rather
                # than "searched for renewal_date".
                parts.append(
                    matching[0].present_label() if present else matching[0].past_label()
                )
            else:
                counted = describe(shape[0], len(matching))
                # An override verb ("Collected") must survive the count, which
                # otherwise falls back to the tool's base verb.
                base = summarize(shape[0], {}).past
                if shape[1] != base and counted.startswith(base):
                    counted = shape[1] + counted[len(base):]
                parts.append(counted)
        return ", ".join(
            part if index == 0 else _lower_first(part)
            for index, part in enumerate(parts)
        )

    if all(call.read_only for call in calls):
        return f"{len(calls)} resource reads"
    return f"{len(calls)} tool calls"


def build_group(calls: list[CallRecord], *, present: bool = False) -> WorkGroup | None:
    """Collapse *calls* into one :class:`WorkGroup` (``None`` when empty)."""
    if not calls:
        return None
    details = _detail_lines(calls)
    return WorkGroup(
        key=calls[0].call_id,
        # A run of *different* read-only tools is a resource sweep, and the
        # search glyph describes it. A single call — or a run of one tool —
        # keeps its own icon, which says more.
        icon=(
            SEARCH
            if len({c.name for c in calls}) > 1 and all(c.read_only for c in calls)
            else icon_for(calls[0].name)
        ),
        label=_compose_label(calls, present=present),
        # A single target already appears in the label; repeating it is noise.
        detail_lines=details if len(details) > 1 else [],
        calls=list(calls),
        running=any(call.status == "running" for call in calls),
    )


# ── Transcript rows ──────────────────────────────────────────────────────


@dataclass(slots=True)
class ProseRow:
    """Something the model said."""

    text: str


@dataclass(slots=True)
class WorkRow:
    """Something the model did."""

    group: WorkGroup


@dataclass(slots=True)
class ApprovalRow:
    """A side-effecting call waiting on you.

    Never collapsed: the description is the thing you have to read in order to
    answer, so hiding it behind a disclosure would add a step before every
    decision. (Cloudflare OS makes the same call, for the same reason.)
    """

    action_id: int
    tool: str
    title: str
    tag: str | None
    auto_approved: bool = False


@dataclass(slots=True)
class DecisionRow:
    """A progress update the agent generated about its own run.

    Distinct from :class:`ProseRow`, which is the model's answer to the user.
    This is narration — "reading the guest list to see who replied" — produced
    by the progress model from observable actions and results only.
    """

    text: str
    kind: str = "decision"          # "decision" | "observation"
    next_action: str = ""
    iteration: Any = None

    @property
    def label(self) -> str:
        return "Decision" if self.kind == "decision" else "Observed"


@dataclass(slots=True)
class ArtifactRow:
    """A file the run produced, as a card rather than a path in a log."""

    path: str
    title: str
    kind: str = "File"
    tool: str = ""

    @property
    def name(self) -> str:
        from pathlib import Path

        return Path(self.path).name


@dataclass(slots=True)
class ConnectionRow:
    """The agent asking you to connect something.

    Never collapsed, for the same reason an approval is not: the reason is
    what you read in order to answer, so hiding it behind a disclosure puts a
    step in front of every decision.
    """

    connection_id: str
    title: str
    reason: str
    auth: str = "unknown"
    tool: str = ""


@dataclass(slots=True)
class SubAgentRow:
    """Work a delegated agent did, attributed to it.

    Rendered indented and labelled, never merged into the parent's own rows:
    a nested `read_file` must not look like the parent read a file.
    """

    agent: str
    task: str
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def group(self) -> WorkGroup | None:
        """The child's calls, collapsed by the same rules as the parent's."""
        return build_group(self.calls)

    @property
    def label(self) -> str:
        group = self.group
        return group.label if group is not None else "worked"

    @property
    def icon(self) -> str:
        group = self.group
        return group.icon if group is not None else TOOL

    @property
    def count(self) -> int:
        return len(self.calls)


@dataclass(slots=True)
class NoticeRow:
    """Something the runtime did — compaction, cancellation, a guardrail."""

    kind: str
    text: str


TranscriptRow = (
    ProseRow
    | WorkRow
    | ApprovalRow
    | ArtifactRow
    | ConnectionRow
    | DecisionRow
    | SubAgentRow
    | NoticeRow
)


_NOTICES = {
    "context_compacted": "Older turns condensed to stay in the context window",
    "run_cancelled": "Cancelled",
    "guardrail_triggered": "Guardrail triggered",
    "lockdown_engaged": "Lockdown — sensitive data was read, so only "
                        "read-only tools may run for the rest of this run",
}


class WorkRunAccumulator:
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
        self.usage: dict[str, int] = {}
        # The tool argument currently being written, keyed by call id, so a
        # live view can show a file appearing rather than nothing until the
        # call completes.
        self.writing: dict[str, str] = {}
        # Work done by delegated agents, keyed by (agent, task).
        self._sub_agents: dict[tuple[str, str], SubAgentRow] = {}

    # ── ingest ───────────────────────────────────────────────────────────

    def feed(self, event: AgentEvent) -> list[TranscriptRow]:
        """Consume one event; return rows that became final because of it."""
        before = len(self._rows)
        self._feed(event)
        return self._rows[before:]

    def _feed(self, event: AgentEvent) -> None:
        payload = event.payload
        kind = event.type

        if kind == "text_delta":
            chunk = str(payload.get("chunk", ""))
            if chunk:
                # Prose breaks a work run — unless the runtime declared the
                # group, in which case the group decides where it ends.
                if self._group_id is None:
                    self._flush_work()
                self._prose.append(chunk)
            return

        if kind == "tool_called":
            # The argument finished streaming; the settled row takes over.
            self.writing.pop(str(payload.get("call_id") or ""), None)
            group = payload.get("group_id")
            if group is not None and group != self._group_id:
                # A new declared group closes the previous one.
                self._flush_work()
                self._group_id = str(group)
            self._flush_prose()
            call = CallRecord(
                call_id=str(payload.get("call_id") or f"call_{len(self._calls)}"),
                name=str(payload.get("tool", "?")),
                arguments=dict(payload.get("arguments") or {}),
                iteration=payload.get("iteration"),
            )
            self._calls.append(call)
            self._by_id[call.call_id] = call
            return

        if kind == "tool_denied":
            # A denied call may never have emitted `tool_called` (the gate can
            # fire first), so this is the only place the prose introducing it
            # gets closed.
            self._flush_prose()

        if kind in ("tool_completed", "tool_failed", "tool_denied"):
            call = self._resolve(payload)
            if call is None:
                return
            call.duration_ms = _as_float(payload.get("duration_ms"))
            if kind == "tool_completed":
                call.status = "ok"
                call.output = str(payload.get("output", "") or "")
            elif kind == "tool_failed":
                call.status = "error"
                call.error = str(payload.get("error", "") or "")
            else:
                call.status = "denied"
                call.error = str(payload.get("reason", "") or "not permitted")
            return

        if kind == "tool_input_started":
            self.writing[str(payload.get("call_id") or "")] = ""
            return

        if kind == "tool_input_delta":
            key = str(payload.get("call_id") or "")
            self.writing[key] = self.writing.get(key, "") + str(payload.get("delta", ""))
            return

        if kind == "sub_agent_event":
            self._feed_sub_agent(payload)
            return

        if kind == "action_queued":
            # An approval interrupts the work run: it is a decision, not a step.
            # Flush prose too — a deferred call never emits `tool_called` (the
            # gate returns before it), so this is the only place the sentence
            # announcing the action gets closed before the card is drawn.
            self._flush_work()
            self._flush_prose()
            self._rows.append(
                ApprovalRow(
                    action_id=int(payload.get("action_id") or 0),
                    tool=str(payload.get("tool", "?")),
                    title=str(payload.get("title") or payload.get("tool", "?")),
                    tag=payload.get("tag"),
                    auto_approved=bool(payload.get("auto_approved")),
                )
            )
            return

        if kind in ("agent_decision", "agent_observation"):
            summary = str(payload.get("summary") or event.message or "").strip()
            if not summary:
                return
            # A decision explains the work that follows, so it closes the run
            # before it; an observation explains the work that just happened,
            # so it closes that one. Both flush, for opposite reasons.
            self._flush_work()
            self._flush_prose()
            self._rows.append(
                DecisionRow(
                    text=summary,
                    kind="decision" if kind == "agent_decision" else "observation",
                    next_action=str(payload.get("next_action") or ""),
                    iteration=payload.get("iteration"),
                )
            )
            return

        if kind == "artifact_created":
            # An artifact belongs after the work that made it and after the
            # sentence introducing it — both settle before the card is drawn,
            # or the prose ends up below the thing it was announcing.
            self._flush_work()
            self._flush_prose()
            self._rows.append(
                ArtifactRow(
                    path=str(payload.get("path") or ""),
                    title=str(payload.get("title") or ""),
                    kind=str(payload.get("kind") or "File"),
                    tool=str(payload.get("tool") or ""),
                )
            )
            return

        if kind == "connection_requested":
            # Like an approval, this interrupts the work run: it is a question
            # for the user, not another step.
            self._flush_work()
            self._flush_prose()
            self._rows.append(
                ConnectionRow(
                    connection_id=str(payload.get("connection_id") or ""),
                    title=str(payload.get("title") or payload.get("connection_id") or ""),
                    reason=str(payload.get("reason") or ""),
                    auth=str(payload.get("auth") or "unknown"),
                    tool=str(payload.get("tool") or ""),
                )
            )
            return

        if kind == "tool_group_completed":
            # The runtime says this batch is done; anything after it belongs
            # to the next row.
            self._flush_work()
            self._group_id = None
            return

        if kind == "usage_tick":
            self.usage = dict(payload.get("usage") or {})
            return

        if kind == "run_completed":
            self.usage = dict(payload.get("usage") or self.usage)
            self._flush_work()
            # An adapter that never streamed deltas hands us the whole answer
            # here; one that did has already given it to us chunk by chunk.
            if not self._prose:
                output = str(payload.get("output", "") or "")
                if output:
                    self._prose.append(output)
            self._flush_prose()
            return

        notice = _NOTICES.get(kind)
        if notice:
            self._flush_work()
            self._flush_prose()
            detail = payload.get("reason") or payload.get("message")
            self._rows.append(
                NoticeRow(kind=kind, text=f"{notice}: {detail}" if detail else notice)
            )

    def _feed_sub_agent(self, payload: dict[str, Any]) -> None:
        """Accumulate a child's tool calls into one attributed row.

        Only the child's *work* is surfaced. Its prose is its own reasoning,
        and the parent already reports the conclusion — showing both would say
        everything twice.
        """
        if payload.get("inner_type") != "tool_called":
            return
        inner = dict(payload.get("inner") or {})
        agent = str(payload.get("agent") or "sub-agent")
        task = str(payload.get("task") or "")
        tool = str(inner.get("tool") or "?")

        key = (agent, task)
        row = self._sub_agents.get(key)
        if row is None:
            row = self._sub_agents[key] = SubAgentRow(agent=agent, task=task)
        row.calls.append(
            CallRecord(
                call_id=str(inner.get("call_id") or f"sub_{len(row.calls)}"),
                name=tool,
                arguments=dict(inner.get("arguments") or {}),
                status="ok",
            )
        )

    def _resolve(self, payload: dict[str, Any]) -> CallRecord | None:
        """Match an outcome to its call — by id, else by the newest running call.

        The id is always present in practice; the fallback covers a
        ``tool_denied`` emitted before its ``tool_called`` (the permission
        gate blocks ahead of the call event) and any adapter that drops it.
        """
        call_id = payload.get("call_id")
        if call_id is not None and str(call_id) in self._by_id:
            return self._by_id[str(call_id)]
        name = payload.get("tool")
        for call in reversed(self._calls):
            if call.status == "running" and (name is None or call.name == name):
                return call
        if name:
            # A gate that fired before the call was announced: synthesize the
            # record so the block still shows up in the transcript.
            call = CallRecord(
                call_id=str(call_id or f"gate_{len(self._calls)}"), name=str(name)
            )
            self._calls.append(call)
            self._by_id[call.call_id] = call
            return call
        return None

    # ── flush ────────────────────────────────────────────────────────────

    def _flush_work(self) -> None:
        group = build_group(self._calls)
        if group is not None:
            self._rows.append(WorkRow(group))
        # A child's work belongs under the delegation that started it.
        for row in self._sub_agents.values():
            self._rows.append(row)
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
        for row in self._sub_agents.values():
            rows.append(row)
        text = self.streaming_text
        if text.strip():
            rows.append(ProseRow(text))
        return rows

    def finish(self) -> list[TranscriptRow]:
        """Close out anything still buffered and return the new rows."""
        before = len(self._rows)
        self._flush_work()
        self._flush_prose()
        return self._rows[before:]

    @property
    def rows(self) -> list[TranscriptRow]:
        return list(self._rows)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
