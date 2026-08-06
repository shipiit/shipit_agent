from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from shipit_agent.models import Message, ToolCall


def coerce_message(message: Any) -> Message:
    """Coerce a raw ``dict`` message into a :class:`Message`.

    Some callers (notably ``ComputerUseAgent``) build plain ``{"role": ...,
    "content": ...}`` dicts — possibly with multimodal list content. Adapters
    access ``message.role`` etc., which would raise ``'dict' object has no
    attribute 'role'``. This makes every adapter accept dict messages. Already
    a :class:`Message`? Returned unchanged.
    """
    if isinstance(message, Message):
        return message
    if isinstance(message, dict):
        return Message(
            role=message.get("role", "user"),
            content=message.get("content", ""),
            name=message.get("name"),
            metadata=dict(message.get("metadata") or {}),
        )
    return message


def coerce_messages(messages: Any) -> list[Message]:
    """Coerce a list that may contain dict messages into ``list[Message]``."""
    return [coerce_message(m) for m in (messages or [])]


def accepts_kwarg(complete_fn: Any, name: str) -> bool:
    """Does ``complete_fn`` accept the keyword *name*?

    Adapters are duck-typed and long-lived; a new optional kwarg must never
    break one written against an older signature. ``**kwargs`` counts as
    acceptance — such an adapter can ignore what it doesn't understand.
    """
    try:
        sig = inspect.signature(complete_fn)
    except (ValueError, TypeError):
        return False
    params = sig.parameters
    if name in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def accepts_tool_input_callback(complete_fn: Any) -> bool:
    """Can this adapter stream a tool call's arguments as they are written?

    Requires the parameter to be **named explicitly** — unlike
    ``accepts_text_delta_callback``, a bare ``**kwargs`` does not count. Some
    adapters are thin wrappers that forward ``**kwargs`` verbatim to an inner
    adapter, so treating that as support pushes an unknown keyword one level
    down and raises there instead. Explicit opt-in is the only safe signal for
    a newly added kwarg.

    Only Anthropic opts in today; everywhere else arguments arrive whole,
    which is the pre-existing behaviour.
    """
    try:
        sig = inspect.signature(complete_fn)
    except (ValueError, TypeError):
        return False
    return "tool_input_callback" in sig.parameters


def accepts_text_delta_callback(complete_fn: Any) -> bool:
    """Return True if ``complete_fn`` accepts a ``text_delta_callback`` kwarg.

    The inline-streaming feature (v1.0.9) passes ``text_delta_callback`` to
    ``LLM.complete``. Older / custom adapters written against the previous
    protocol signature don't accept it, so the runtime must detect support
    before passing the kwarg — otherwise it raises ``TypeError`` and the
    model is never called. Adapters that accept ``**kwargs`` are treated as
    supporting it (they can ignore it safely).
    """
    try:
        sig = inspect.signature(complete_fn)
    except (ValueError, TypeError):
        # Builtins / C-level callables with no introspectable signature:
        # assume unsupported so we fall back to the safe call shape.
        return False
    params = sig.parameters
    if "text_delta_callback" in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


@dataclass(slots=True)
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class LLM(Protocol):
    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
        # (tool_call_id, tool_name, raw_json_delta). Optional: adapters that
        # cannot surface partial tool arguments simply don't accept it.
        tool_input_callback: Callable[[str, str, str], None] | None = None,
    ) -> LLMResponse: ...
