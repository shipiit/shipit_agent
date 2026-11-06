"""Tool calls as recorded, and how a run of them becomes one labelled group."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..verbs import (
    SEARCH,
    describe_count,
    describe_count_present,
    icon_for,
    is_read_only,
    summarize,
)

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
