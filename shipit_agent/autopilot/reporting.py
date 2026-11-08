"""Autopilot heartbeats, critic feedback, results and stop handling."""

from __future__ import annotations

from typing import Any

from .budget import BudgetUsage
from .critic import CriticVerdict
from .result import AutopilotResult


class _AutopilotReporting:
    """Autopilot heartbeats, critic feedback, results and stop handling."""

    def _emit_heartbeat(
        self, usage: BudgetUsage, criteria_met: list[bool], last_summary: str
    ) -> None:
        if not self.on_heartbeat:
            return
        payload = {
            "iteration": usage.iterations,
            "usage": usage.to_dict(),
            "remaining": self.budget.remaining(usage),
            "criteria_met": criteria_met,
            "criteria_satisfied_count": sum(1 for c in criteria_met if c),
            "criteria_total": len(criteria_met),
            "last_summary": last_summary,
        }
        try:
            self.on_heartbeat(payload)
        except Exception:  # noqa: BLE001
            pass

    def _stash_critic_suggestions(self, verdict: CriticVerdict) -> None:
        """Snapshot the latest verdict AND (when useful) feed its suggestions
        into the next inner-agent invocation's prompt.

        GoalAgent accepts a ``prompt`` kwarg — we mutate it in-place so the
        next iteration sees the feedback. Restored each iteration so stale
        suggestions don't accumulate across runs.
        """
        # Always snapshot the verdict — the final AutopilotResult surfaces
        # it regardless of whether the critic produced suggestions.
        self._last_verdict = verdict

        if not verdict.suggestions:
            self.agent_kwargs.pop("_critic_injected_prompt", None)
            return
        from .critic import inject_suggestions_into_prompt

        base = (
            self.agent_kwargs.get("prompt")
            or "You are a helpful assistant. Complete the task thoroughly."
        )
        self.agent_kwargs["prompt"] = inject_suggestions_into_prompt(base, verdict)
        self.agent_kwargs["_critic_injected_prompt"] = True

    def _make_awaiting_result(
        self,
        run_id: str,
        usage: BudgetUsage,
        criteria_met: list[bool],
        output: str,
        halt_reason: str,
        step_outputs: list[dict[str, Any]],
    ) -> AutopilotResult:
        """Short-circuit factory for the `awaiting_user` halt status."""
        return AutopilotResult(
            run_id=run_id,
            status="awaiting_user",
            goal=self.goal_dict(),
            criteria_met=criteria_met,
            iterations=usage.iterations,
            usage=usage.to_dict(),
            output=output,
            halt_reason=halt_reason,
            step_outputs=step_outputs,
            artifacts=[a.to_dict() for a in self.artifacts.all()]
            if self.artifacts
            else [],
        )

    def _make_result(
        self,
        run_id: str,
        status: str,
        criteria_met: list[bool],
        usage: BudgetUsage,
        output: str,
        halt_reason: str,
        step_outputs: list[dict[str, Any]],
    ) -> AutopilotResult:
        verdict = getattr(self, "_last_verdict", None)
        return AutopilotResult(
            run_id=run_id,
            status=status,
            criteria_met=criteria_met,
            iterations=usage.iterations,
            usage=usage.to_dict(),
            output=output,
            halt_reason=halt_reason,
            step_outputs=step_outputs,
            artifacts=[a.to_dict() for a in self.artifacts.all()]
            if self.artifacts
            else [],
            critic_verdict=verdict.to_dict() if verdict else {},
        )

    def request_stop(self, reason: str = "stop requested") -> None:
        """Ask the loop to halt cleanly at the next iteration boundary.

        Safe to call from any thread or a signal handler. The loop
        finishes the current iteration's save, then exits normally with
        ``halt_reason`` set to ``reason``.
        """
        self._stop_requested = reason
