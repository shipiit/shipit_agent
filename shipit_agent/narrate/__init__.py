"""The Narrator — turn an agent's event stream into readable prose.

Stage 1 of the modern-agent upgrade (see ``docs/design/modern-agent-upgrade.md``).
Presentation only: nothing here changes what the agent does, just how a run
reads. ``verbs`` is the vocabulary; ``grouping`` and ``renderer`` land next.
"""

from .grouping import (
    ApprovalRow,
    CallRecord,
    NoticeRow,
    ProseRow,
    SubAgentRow,
    TranscriptRow,
    WorkGroup,
    WorkRow,
    WorkRunAccumulator,
    build_group,
    build_transcript,
)
from .json_stream import StreamingToolInputParser, streaming_field_for
from .live_ui import LiveView, render_chat_html, watch, watch_tree
from .timeline import TimelineBuilder, render_markdown, stream_timeline, timeline
from .renderer import LiveRegion, NarratorRenderer, render_transcript
from .tree import TreeRenderer, render_tree
from .share import render_transcript_html, transcript_json, write_transcript
from .verbs import (
    VERBS,
    ToolSummary,
    VerbSpec,
    describe_count,
    describe_count_present,
    icon_for,
    is_read_only,
    pluralize,
    register_verb,
    register_verbs,
    registered_verbs,
    spec_for,
    summarize,
    unregister_verb,
)

__all__ = [
    # vocabulary
    "VERBS",
    "ToolSummary",
    "VerbSpec",
    "describe_count",
    "describe_count_present",
    "icon_for",
    "is_read_only",
    "pluralize",
    "register_verb",
    "register_verbs",
    "registered_verbs",
    "spec_for",
    "summarize",
    "unregister_verb",
    # grouping
    "ApprovalRow",
    "CallRecord",
    "NoticeRow",
    "ProseRow",
    "SubAgentRow",
    "TranscriptRow",
    "WorkGroup",
    "WorkRow",
    "WorkRunAccumulator",
    "build_group",
    "build_transcript",
    # rendering
    "LiveRegion",
    "LiveView",
    "render_chat_html",
    "watch",
    "watch_tree",
    "TimelineBuilder",
    "timeline",
    "stream_timeline",
    "render_markdown",
    "TreeRenderer",
    "render_tree",
    "NarratorRenderer",
    "render_transcript",
    "render_transcript_html",
    "transcript_json",
    "write_transcript",
    "StreamingToolInputParser",
    "streaming_field_for",
]
