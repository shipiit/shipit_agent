from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from typing import Any, Callable

from shipit_agent.permissions import PermissionDecision, PermissionResult


def _coerce_hook_decision(value: Any) -> PermissionResult | None:
    """Normalize whatever a before-tool hook returned into a PermissionResult.

    Accepts ``None`` (no opinion / observe-only), a ``PermissionResult``, a
    ``bool`` (``False`` → deny), or a dict like
    ``{"decision": "deny", "reason": "...", "updated_arguments": {...}}``.
    """
    if value is None:
        return None
    if isinstance(value, PermissionResult):
        return value
    if isinstance(value, bool):
        return (
            None
            if value
            else PermissionResult(PermissionDecision.DENY, reason="hook returned False")
        )
    if isinstance(value, dict) and "decision" in value:
        return PermissionResult(
            PermissionDecision(str(value["decision"]).lower()),
            reason=str(value.get("reason", "")),
            updated_arguments=value.get("updated_arguments"),
        )
    return None


@dataclass(slots=True)
class AgentHooks:
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

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def run_before_llm(self, messages: list[Any], tools: list[Any]) -> None:
        for fn in self.before_llm:
            fn(messages, tools)

    def run_after_llm(self, response: Any) -> None:
        for fn in self.after_llm:
            fn(response)

    def run_before_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> PermissionResult | None:
        """Run before-tool hooks and fold their decisions together.

        Precedence: a DENY wins; otherwise an ASK; otherwise the last
        ``updated_arguments`` rewrite is applied on an ALLOW. Returns ``None``
        when every hook is observe-only (backward compatible).
        """
        outcome: PermissionResult | None = None
        for fn in self.before_tool:
            decision = _coerce_hook_decision(fn(name, arguments))
            if decision is None:
                continue
            if decision.denied:
                return decision  # short-circuit on the first hard deny
            if decision.needs_approval:
                outcome = decision
            elif outcome is None or not outcome.needs_approval:
                # ALLOW (possibly with a rewrite) — keep unless an ASK stands.
                outcome = decision
        return outcome

    def run_after_tool(self, name: str, result: Any) -> Any:
        """Run post-tool hooks, allowing each to replace or sanitize output."""
        current = result
        for fn in self.after_tool:
            value = fn(name, current)
            if value is None:
                continue
            if isinstance(value, str) and hasattr(current, "output"):
                current.output = value
                continue
            if isinstance(value, dict) and hasattr(current, "output"):
                if "output" in value or "text" in value:
                    current.output = str(value.get("output", value.get("text", "")))
                if isinstance(value.get("metadata"), dict):
                    current.metadata.update(value["metadata"])
                continue
            if hasattr(value, "text") and hasattr(current, "output"):
                current.output = str(value.text)
                current.metadata.update(dict(getattr(value, "metadata", {}) or {}))
                continue
            if hasattr(value, "output"):
                current = value
        return current

    def run_user_prompt(self, prompt: str) -> tuple[str, PermissionResult | None]:
        """Let hooks rewrite or block the user prompt.

        Returns ``(possibly_rewritten_prompt, decision_or_None)``. A returned
        string rewrites the prompt; a deny decision (``False`` or a dict/result)
        blocks the run.
        """
        current = prompt
        for fn in self.user_prompt:
            value = fn(current)
            if isinstance(value, str):
                current = value
                continue
            decision = _coerce_hook_decision(value)
            if decision is not None and decision.denied:
                return current, decision
        return current, None
