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

The package: ``calls`` (call records and how a run of them is labelled),
``rows`` (the row types), ``accumulator`` with its ``tool_events`` and
``card_events`` mixins (events in, rows out).
"""

from .accumulator import WorkRunAccumulator, build_transcript
from .calls import CallRecord, CallStatus, WorkGroup, build_group
from .rows import (
    ApprovalRow,
    ArtifactRow,
    ConnectionRow,
    DecisionRow,
    NoticeRow,
    ProseRow,
    SubAgentRow,
    TranscriptRow,
    WorkRow,
)

__all__ = [
    "CallRecord",
    "CallStatus",
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
