from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from shipit_agent.models import Message, ToolCall


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
    ) -> LLMResponse: ...
