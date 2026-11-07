"""The messages a :func:`~shipit_agent.sdk.query` yields, shaped like the Claude Agent SDK's.

A run is a sequence of these: a ``SystemMessage`` (``init``) first, then
``AssistantMessage`` and ``UserMessage`` (tool results) as the agent works,
optionally ``StreamEvent`` deltas, and one ``ResultMessage`` last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

__all__ = [
    "AssistantMessage",
    "ContentBlock",
    "Message",
    "ResultMessage",
    "StreamEvent",
    "SystemMessage",
    "TextBlock",
    "ThinkingBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "UserMessage",
]


@dataclass(slots=True)
class TextBlock:
    """Text the model wrote."""

    text: str


@dataclass(slots=True)
class ThinkingBlock:
    """The model's reasoning, when the model and provider expose it."""

    thinking: str
    signature: str = ""


@dataclass(slots=True)
class ToolUseBlock:
    """A tool call the model made."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResultBlock:
    """What a tool call returned (or why it did not run)."""

    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None


ContentBlock = Union[TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock]


@dataclass(slots=True)
class UserMessage:
    """A user turn: the prompt, or the results of the model's tool calls."""

    content: str | list[ContentBlock]
    uuid: str | None = None
    parent_tool_use_id: str | None = None


@dataclass(slots=True)
class AssistantMessage:
    """One model response: its text, thinking and tool calls."""

    content: list[ContentBlock]
    model: str
    parent_tool_use_id: str | None = None
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    uuid: str | None = None


@dataclass(slots=True)
class SystemMessage:
    """Something about the session rather than the conversation.

    ``subtype`` is ``init`` (the session's model, tools and settings),
    ``compact_boundary``, ``api_retry``, ``model_fallback``,
    ``task_started`` or ``task_notification`` (sub-agents); ``data`` holds
    the details.
    """

    subtype: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResultMessage:
    """The last message of a run: how it ended, what it cost, and the answer."""

    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    stop_reason: str | None = None
    permission_denials: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: The call a hook deferred; resume the session to settle it.
    deferred_tool_use: dict[str, Any] | None = None


@dataclass(slots=True)
class StreamEvent:
    """A partial update while a response streams (``include_partial_messages``)."""

    uuid: str
    session_id: str
    event: dict[str, Any]
    parent_tool_use_id: str | None = None


Message = Union[UserMessage, AssistantMessage, SystemMessage, ResultMessage, StreamEvent]
