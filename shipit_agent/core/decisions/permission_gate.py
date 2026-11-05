"""The permission gate: whether a tool call may run, and latching lockdown when a run turns risky.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.safety.permissions import (
    PermissionDecision,
    PermissionResult,
    authorize_tool,
)


class PermissionGateMixin:
    """The permission gate: whether a tool call may run, and latching lockdown when a run turns risky."""

    def authorize(
        self, name: str, arguments: dict[str, Any], tool: Any
    ) -> PermissionResult | None:
        """Lockdown, then guardrail tool rules, then hooks and the engine.

        Order matters and is the security contract: lockdown outranks
        everything (no configuration set before a sensitive read may authorize
        an action after it), and a content-level guardrail deny beats any
        allow rule.
        """
        if self.lockdown.engaged:
            from shipit_agent.tools.contracts import contract_for

            if self.lockdown.blocks(name, read_only=contract_for(name, tool).read_only):
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=self.lockdown.denial_reason(name),
                )

        if self.guardrails is not None:
            ceiling = getattr(self.guardrails, "max_tool_calls", 0)
            if ceiling and self._guarded_tool_calls >= ceiling:
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=f"guardrail: tool-call ceiling ({ceiling}) reached",
                )
            guard = self.guardrails.check_tool(name, arguments)
            if guard is not None and not guard.allowed:
                return guard
            self._guarded_tool_calls += 1

        risk: tuple[str, ...] = ()
        assess = getattr(tool, "assess_command", None)
        if callable(assess):
            verdict = assess(arguments)
            if verdict.level == "blocked":
                return PermissionResult(
                    decision=PermissionDecision.DENY, reason="; ".join(verdict.reasons)
                )
            risk = tuple(verdict.reasons) if verdict.level == "risky" else ()
        decision = authorize_tool(
            self.hooks, self.permissions, name, arguments, tool, risk=risk
        )
        if decision is not None and decision.needs_approval and self.hooks:
            settled = self.hooks.run_permission_request(name, arguments, decision.reason)
            if settled is not None:
                return settled
            self.hooks.run_notification(
                f"'{name}' needs approval: {decision.reason}", "permission_prompt"
            )
        return decision

    def note_lockdown(
        self,
        state: Any,
        *,
        tool: str,
        arguments: dict[str, Any],
        output_metadata: dict[str, Any],
        redacted_secret: bool,
        iteration: int,
    ) -> None:
        """Evaluate a completed call for sensitivity; emit if it latched."""
        trigger = self.lockdown.observe(
            tool=tool,
            arguments=arguments,
            output_metadata=output_metadata,
            redacted_secret=redacted_secret,
        )
        if trigger is not None:
            self.emit(
                state,
                "lockdown_engaged",
                f"Lockdown: {trigger.reason}",
                reason=trigger.reason,
                tool=trigger.tool,
                source=trigger.source,
                iteration=iteration,
            )
