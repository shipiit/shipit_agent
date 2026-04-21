"""Autopilot — long-running "keep working until the goal is met" runtime.

Public surface:

  - :class:`Autopilot`            — the driver class with ``run()``, ``resume()``,
                                    and ``stream()`` methods.
  - :class:`BudgetPolicy`         — wall-clock / token / cost / tool-call caps.
  - :class:`BudgetUsage`          — running totals the driver updates.
  - :class:`AutopilotResult`      — the final envelope returned by ``run()``.
  - ``default_heartbeat_stderr``  — a sensible stderr sink for heartbeats.
  - ``coerce_event``              — normalize inner-agent events into ``{"kind"...}``.

Typical use::

    from shipit_agent import Autopilot, BudgetPolicy, Goal, default_heartbeat_stderr

    autopilot = Autopilot(
        llm=llm,
        goal=Goal(
            objective="Migrate every SQL query in src/ to parameterized form",
            success_criteria=[
                "No raw string concatenation remains in .sql calls",
                "All tests pass",
            ],
        ),
        budget=BudgetPolicy(max_seconds=3600, max_tool_calls=200),
        on_heartbeat=default_heartbeat_stderr,
    )
    for event in autopilot.stream(run_id="sql-migration"):
        print(event["kind"], event.get("iteration", ""))
"""

from .artifacts import Artifact, ArtifactCollector
from .budget import BudgetPolicy, BudgetUsage
from .checkpoint import CheckpointStore
from .core import Autopilot
from .critic import Critic, CriticVerdict, inject_suggestions_into_prompt
from .events import coerce_event, default_heartbeat_stderr
from .result import AutopilotResult

# Import streaming + fanout for their side-effect: they attach
# `Autopilot.stream()` / `Autopilot.fanout()` / `Autopilot.fanout_stream()`.
# Without these, callers get AttributeError.
from . import streaming as _streaming  # noqa: F401
from . import fanout as _fanout  # noqa: F401
from .fanout import FanoutResult

__all__ = [
    "Autopilot",
    "AutopilotResult",
    "Artifact",
    "ArtifactCollector",
    "BudgetPolicy",
    "BudgetUsage",
    "CheckpointStore",
    "Critic",
    "CriticVerdict",
    "FanoutResult",
    "coerce_event",
    "default_heartbeat_stderr",
    "inject_suggestions_into_prompt",
]
