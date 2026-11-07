"""The run as a **timeline** — the event shape a frontend actually wants.

:meth:`Agent.stream` is the runtime's own vocabulary: every text delta, every
retry, every partial argument. That is the right feed for a renderer and the
wrong one for a UI, which wants to draw four things — a summary of what the
agent set out to do, groups of tool calls, the decisions between them, and the
final answer.

This module translates one into the other::

    for step in stream_timeline(agent, "Process the latest RSVP"):
        socket.send(json.dumps(step))

    # {"type": "run_started",         "goal": "Process the latest RSVP"}
    # {"type": "tool_group_started",  "group_id": "g1", "title": "Reading 2 files"}
    # {"type": "tool_call_started",   "tool_call_id": "1", "tool_name": "read_file", …}
    # {"type": "tool_call_completed", "tool_call_id": "1", "status": "completed", …}
    # {"type": "tool_group_completed","group_id": "g1", "title": "Read 2 files"}
    # {"type": "agent_decision",      "content": "…", "next_action": "call_tool"}
    # {"type": "final_response",      "content": "…", "tool_calls": 4}

Three properties it is built to hold:

**Causal.** Every step is emitted from information that already exists. A
group's settled title arrives in ``tool_group_completed``, not retroactively
patched into the ``started`` event — a client that has already drawn a row
never has to undraw it.

**JSON, not objects.** Every step is a plain dict of primitives, so it goes
onto a socket, into a log, or through :mod:`shipit_agent.streaming` unchanged.

**No hidden reasoning.** ``agent_decision`` carries the prose the model
actually emitted between tool calls — the same text a user sees in the
transcript. Nothing private is exposed, because nothing private is read.

:func:`render_markdown` prints the same timeline as a report, for a PR comment
or a run log.

The package: ``builder`` (TimelineBuilder), ``events`` (what each event
becomes), ``markdown`` (the report) and ``values``.
"""

from __future__ import annotations

from .builder import TimelineBuilder, stream_timeline, timeline
from .markdown import render_markdown

__all__ = [
    "TimelineBuilder",
    "render_markdown",
    "stream_timeline",
    "timeline",
]
