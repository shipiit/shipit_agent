"""The values that move through a run.

The one change here that matters more than the rest: **a tool call carries its
own id**. Providers correlate a call to its result by id — Bedrock rejects a
multi-step run with "Expected toolResult blocks for Ids: …" when the pairing is
absent — and an id that lives in a loose ``metadata`` dict is an id that the
type system cannot check, that a helper holding only a :class:`ToolCall` cannot
reach, and that every adapter has to rediscover.

Carrying it as a field has three consequences worth naming:

* **No history rewriting.** With correct pairing emitted directly, the SDK no
  longer has to patch requests by inserting filler turns. Those insertions
  polluted context, cost tokens on every subsequent turn, and — since implicit
  prompt caching keys on a stable prefix — silently destroyed every cache hit
  for the rest of the conversation.
* **Parallel calls are unambiguous.** Two concurrent calls to the same tool are
  distinguishable, which they are not when a name is the only handle.
* **Runs can be resumed.** A checkpoint can name the call it stopped on.

Ids are also mirrored into ``metadata`` on serialisation, so adapters written
against the old shape keep working through one release. Read the field; write
both.
"""

from __future__ import annotations

from shipit_agent.core.result_subtype import ResultSubtype, result_subtype

from .kinds import EventType, Role
from .message import Message, TextPart, ToolCallPart, pair_calls_and_results
from .results import AgentEvent, AgentResult, Artifact
from .tool_calls import ToolCall, ToolResult, new_tool_call_id

__all__ = [
    "ResultSubtype",
    "result_subtype",
    "AgentEvent",
    "AgentResult",
    "Artifact",
    "EventType",
    "Message",
    "Role",
    "TextPart",
    "ToolCall",
    "ToolCallPart",
    "ToolResult",
    "new_tool_call_id",
    "pair_calls_and_results",
]
