"""AgentHooks: the callbacks registered for each lifecycle event."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .dispatch import HookDispatchMixin
from .registration import HookRegistrationMixin


@dataclass(slots=True)
class AgentHooks(HookRegistrationMixin, HookDispatchMixin):
    """Lifecycle hooks for an agent — observe, **and now block or rewrite**.

    Attach callbacks around LLM calls, tool calls, and the user prompt. Unlike
    pure logging hooks, a ``before_tool`` hook may **return a decision** to
    deny a tool call, require approval, or rewrite its arguments (Claude
    Code-style ``PreToolUse``):

        hooks = AgentHooks()

        @hooks.on_before_tool
        def guard(name, args):
            if name == "bash" and "rm -rf" in args.get("command", ""):
                return {"decision": "deny", "reason": "destructive command"}
            # return None to allow (observe-only — fully backward compatible)

        @hooks.on_user_prompt
        def redact(prompt):
            return prompt.replace("SECRET", "[redacted]")  # rewrite the prompt

    Returning ``None`` from any hook preserves the old observe-only behaviour.
    """

    before_llm: list[Callable[..., Any]] = field(default_factory=list)
    after_llm: list[Callable[..., Any]] = field(default_factory=list)
    before_tool: list[Callable[..., Any]] = field(default_factory=list)
    after_tool: list[Callable[..., Any]] = field(default_factory=list)
    user_prompt: list[Callable[..., Any]] = field(default_factory=list)
    stop: list[Callable[..., Any]] = field(default_factory=list)
    pre_compact: list[Callable[..., Any]] = field(default_factory=list)
    subagent_start: list[Callable[..., Any]] = field(default_factory=list)
    subagent_stop: list[Callable[..., Any]] = field(default_factory=list)
