"""What a sub-agent run reports back, and the shared-state keys the parent publishes.

The runtime publishes the parent's tools and control plane under
:data:`PARENT_STATE_KEY`, an event sink under :data:`EVENT_SINK_KEY`, and the
delegation depth under :data:`DEPTH_STATE_KEY`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The runtime publishes the parent's tools and control plane here so a child
# can be built that is strictly no more capable.
PARENT_STATE_KEY = "subagent_parent"
# The runtime publishes an event sink here so a child's work is visible in
# the parent's transcript instead of vanishing into a black box.
EVENT_SINK_KEY = "subagent_event_sink"
DEPTH_STATE_KEY = "subagent_depth"

# How deep delegation may go. Without a cap, a model that likes delegating
# spawns a subagent that spawns a subagent, and the run never terminates.
MAX_DEPTH = 2


# A subagent that hasn't finished in this many turns is not going to.
DEFAULT_MAX_ITERATIONS = 12

# Tools a subagent never gets, regardless of what the parent holds.
_NEVER_INHERITED = frozenset(
    {
        # Recursion is capped by depth, but a subagent asking the *human* a
        # question is worse: the parent is mid-turn and nobody is watching the
        # child's stdout.
        "ask_user",
        "ask_user_async",
        "human_review",
    }
)


def _state(context: Any, attribute: str) -> dict[str, Any]:
    """Read a mapping off the context, tolerating duck-typed stand-ins.

    Tools are handed a real ``ToolContext``, but embedders and tests pass
    lighter objects; a missing attribute should not be the difference between
    delegating and raising.
    """
    value = getattr(context, attribute, None)
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class SubAgentResult:
    """What a delegated task produced."""

    task: str
    output: str
    agent_type: str | None = None
    iterations: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    gave_up: bool = False
    give_up_reason: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.gave_up

    def report(self) -> str:
        """What the parent sees — the answer, plus why if it failed."""
        if self.error:
            return f"Sub-agent failed: {self.error}"
        if self.gave_up:
            return f"Sub-agent could not complete the task: {self.give_up_reason}"
        return self.output or "(the sub-agent produced no output)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "agent_type": self.agent_type,
            "ok": self.ok,
            "iterations": self.iterations,
            # NOT "tool_calls": the runtime reserves that key on message
            # metadata for the assistant's tool-call *records*, and a tool
            # result's metadata is merged onto its message. An int there makes
            # the LiteLLM serializer iterate an integer.
            "tool_call_count": self.tool_calls,
            "usage": dict(self.usage),
            "gave_up": self.gave_up,
            "error": self.error,
            # Retained from the original tool's contract.
            "delegated": True,
        }
