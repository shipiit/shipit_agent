"""Registering hooks: one decorator per lifecycle event."""

from __future__ import annotations

import fnmatch
from typing import Any, Callable


class HookRegistrationMixin:
    """The ``on_*`` decorators of :class:`~shipit_agent.safety.hooks.AgentHooks`."""

    __slots__ = ()

    # ------------------------------------------------------------------
    # Registration decorators
    # ------------------------------------------------------------------
    def on_before_llm(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.before_llm.append(fn)
        return fn

    def on_after_llm(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.after_llm.append(fn)
        return fn

    def on_before_tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.before_tool.append(fn)
        return fn

    def on_after_tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.after_tool.append(fn)
        return fn

    def on_before_tool_matching(
        self, matcher: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a before-tool hook for a glob or ``|``-separated globs."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            patterns = [part.strip() for part in matcher.split("|") if part.strip()]

            def matched(name: str, arguments: dict[str, Any]) -> Any:
                if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    return fn(name, arguments)
                return None

            self.before_tool.append(matched)
            return fn

        return decorator

    def on_after_tool_matching(
        self, matcher: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register an output-transforming hook for matching tool names."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            patterns = [part.strip() for part in matcher.split("|") if part.strip()]

            def matched(name: str, result: Any) -> Any:
                if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    return fn(name, result)
                return None

            self.after_tool.append(matched)
            return fn

        return decorator

    def on_user_prompt(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook that can rewrite or block the incoming user prompt."""
        self.user_prompt.append(fn)
        return fn

    def on_stop(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook that can keep the agent working when it tries to finish.

        Called with the answer the agent is about to give. Return ``None`` to
        let it finish, or a reason (a string, or ``{"decision": "block",
        "reason": "..."}``) to send it back to work with that reason — Claude
        Code-style ``Stop`` hooks. The runtime caps how often this can happen
        in one run, so a hook that never relents cannot loop forever.
        """
        self.stop.append(fn)
        return fn

    def on_subagent_start(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook that runs before a sub-agent is started.

        Called with ``(agent_type, task)``. Return ``False`` or a deny decision
        to refuse the delegation, text to add to the sub-agent's brief, or
        ``None`` to let it run as asked.
        """
        self.subagent_start.append(fn)
        return fn

    def on_subagent_stop(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called with ``(agent_type, task, output, error)`` when a sub-agent ends."""
        self.subagent_stop.append(fn)
        return fn

    def on_pre_compact(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook that runs just before older turns are summarized.

        Called with a copy of the messages and ``{"trigger", "estimated_tokens",
        "budget_tokens"}``, like Claude's ``PreCompact`` hook: archive the full
        transcript, or return text to add to the summarizer's instructions
        (what the handoff must keep). Return ``None`` to change nothing.
        """
        self.pre_compact.append(fn)
        return fn

    def on_post_tool_failure(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called with ``(name, arguments, error)`` when a tool fails.

        Like the SDK's ``PostToolUseFailure``: return text to add to what the
        model reads with the failed result (how to recover, say), or ``None``.
        After-tool hooks still run for the failure too.
        """
        self.post_tool_failure.append(fn)
        return fn

    def on_permission_request(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook that settles a call which would wait for approval.

        Called with ``(name, arguments, reason)`` once rules, mode and the
        permission callback have left the call needing a human, like the SDK's
        ``PermissionRequest``. Return ``{"decision": "allow"}`` (or a
        ``PermissionResult``, which may carry ``updated_arguments``) to run it,
        ``{"decision": "deny", "reason": ...}`` or ``False`` to refuse it, or
        ``None`` to leave it waiting.
        """
        self.permission_request.append(fn)
        return fn

    def on_notification(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called with ``(message, notification_type)``.

        Fires with ``"permission_prompt"`` when a call is left waiting for a
        human's approval, so a host can page someone. It only observes.
        """
        self.notification.append(fn)
        return fn
