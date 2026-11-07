"""The rows a transcript is made of: prose, work, and the cards between them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..verbs import TOOL
from .calls import CallRecord, WorkGroup, build_group


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
