"""Running hooks: each event's callbacks, and how their answers combine."""

from __future__ import annotations

from typing import Any

from shipit_agent.safety.permissions import PermissionResult

from .decisions import _coerce_hook_decision


class HookDispatchMixin:
    """The ``run_*`` methods of :class:`~shipit_agent.safety.hooks.AgentHooks`."""

    __slots__ = ()

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

    def run_stop(self, answer: str) -> str | None:
        """The first reason a stop hook gives to keep going, or ``None``."""
        for fn in self.stop:
            value = fn(answer)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict) and str(value.get("decision", "")).lower() in (
                "block",
                "continue",
            ):
                return str(
                    value.get("reason") or "The task is not finished yet."
                ).strip()
        return None

    def run_subagent_start(self, agent_type: str, task: str) -> tuple[bool, str, str]:
        """Run start hooks: ``(allowed, refusal_reason, extra_context)``."""
        notes: list[str] = []
        for fn in self.subagent_start:
            value = fn(agent_type, task)
            if value is False:
                return False, "a sub-agent start hook refused it", ""
            if isinstance(value, str):
                if value.strip():
                    notes.append(value.strip())
                continue
            decision = _coerce_hook_decision(value)
            if decision is not None and decision.denied:
                return False, decision.reason or "a sub-agent start hook refused it", ""
        return True, "", "\n".join(notes)

    def run_subagent_stop(
        self, agent_type: str, task: str, output: str, error: str
    ) -> None:
        """Run stop hooks; they observe and cannot change the result."""
        for fn in self.subagent_stop:
            fn(agent_type, task, output, error)

    def run_pre_compact(self, messages: list[Any], info: dict[str, Any]) -> str:
        """Run pre-compact hooks; the instructions they return, joined."""
        notes: list[str] = []
        for fn in self.pre_compact:
            value = fn(list(messages), dict(info))
            if isinstance(value, str) and value.strip():
                notes.append(value.strip())
        return "\n".join(notes)

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

    def run_post_tool_failure(self, name: str, arguments: dict[str, Any], error: str) -> str:
        """Run failure hooks; the context they return, joined."""
        notes: list[str] = []
        for fn in self.post_tool_failure:
            value = fn(name, dict(arguments), error)
            if isinstance(value, str) and value.strip():
                notes.append(value.strip())
        return "\n".join(notes)

    def run_permission_request(
        self, name: str, arguments: dict[str, Any], reason: str
    ) -> PermissionResult | None:
        """The first allow or deny a request hook gives, or ``None`` to keep waiting."""
        for fn in self.permission_request:
            decision = _coerce_hook_decision(fn(name, dict(arguments), reason))
            if decision is not None and not decision.needs_approval:
                return decision
        return None

    def run_notification(self, message: str, notification_type: str) -> None:
        for fn in self.notification:
            fn(message, notification_type)
