"""Time-Travel Replay — load any saved trace, fork from any event, re-run.

Three things you get:

1. **Inspect** — load a saved ``TraceRecord`` (from ``FileTraceStore`` or
   ``InMemoryTraceStore``) and walk its events programmatically.

2. **Fork** — pick any event index and produce a ``ReplayCheckpoint`` that
   captures the conversation state up to that point. Optionally edit the
   prompt or pre-tool args at the fork.

3. **Continue** — feed the checkpoint to a fresh ``Agent`` to resume from
   the fork point with whatever changes you made.

Plus a small ``diff_traces`` helper for side-by-side comparison.

Why this matters: agent debugging today is painful — you read 2000 lines of
logs and guess what went wrong. Time-travel turns it into "click the bad
step, fork, try a different prompt, see if it works". The whole package is
pure Python — no extra deps.

Quick start::

    from shipit_agent.replay import TraceReplayer
    from shipit_agent.tracing import FileTraceStore

    store = FileTraceStore('./traces')
    replayer = TraceReplayer.from_store(store, trace_id='run-2026-05-09-abc')

    # Inspect — what tools fired?
    for i, ev in enumerate(replayer.events):
        if ev.type == 'tool_called':
            print(i, ev.payload.get('tool'))

    # Fork at event 12, with a tweaked user prompt
    fork = replayer.fork(at_event=12, edit_user_message='Try a narrower question.')

    # Resume on a fresh agent
    result = fork.continue_from(agent=my_new_agent)
"""

from __future__ import annotations

from .differ import TraceDiff, diff_traces
from .models import ForkPoint, ReplayCheckpoint, ReplayResult
from .replayer import TraceReplayer

__all__ = [
    "ForkPoint",
    "ReplayCheckpoint",
    "ReplayResult",
    "TraceDiff",
    "TraceReplayer",
    "diff_traces",
]
