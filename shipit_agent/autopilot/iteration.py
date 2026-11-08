"""How Autopilot builds each iteration's inner agent, applies the critic and checkpoints progress."""

from __future__ import annotations

from typing import Any

from shipit_agent.deep.goal_agent import GoalAgent

from .budget import BudgetUsage
from .critic import CriticVerdict
from .pricing import (
    _lookup_dollars as _lookup_dollars,
)
from .pricing import (
    _resolve_pricing as _resolve_pricing,
)


class _AutopilotIteration:
    """How Autopilot builds each iteration's inner agent, applies the critic and checkpoints progress."""

    def goal_dict(self) -> dict[str, Any]:
        return {
            "objective": self.goal.objective,
            "success_criteria": list(self.goal.success_criteria),
            "max_steps": self.goal.max_steps,
        }

    def _build_inner_agent(self) -> Any:
        if self.agent_factory is not None:
            return self.agent_factory(
                llm=self.llm,
                goal=self.goal,
                tools=self.tools,
                mcps=self.mcps,
                **self.agent_kwargs,
            )
        return GoalAgent(
            llm=self.llm,
            tools=list(self.tools),
            mcps=list(self.mcps),
            goal=self.goal,
            use_builtins=self.use_builtins,
            **self.agent_kwargs,
        )

    def _checkpoint(
        self, rid: str, usage: BudgetUsage, step_outputs: list[dict[str, Any]], output: str
    ) -> None:
        self.checkpoints.save(
            rid,
            goal=self.goal_dict(),
            usage=usage,
            step_outputs=step_outputs,
            output=output,
        )

    def _apply_critic(
        self, final_output: str, criteria_met: list[bool]
    ) -> tuple[CriticVerdict, list[bool]]:
        """The critic's verdict on this iteration, and the criteria it settles."""
        if self.critic is None:
            return CriticVerdict(), criteria_met
        verdict = self.critic.review(
            objective=self.goal.objective,
            criteria=self.goal.success_criteria,
            output=final_output,
            fallback_llm=self.llm,
        )
        # Only trust the critic's flag-flips when its stated
        # confidence meets the gate. A low-confidence "yes" is
        # still useful as feedback (suggestions) but shouldn't
        # short-circuit the loop.
        if (
            any(verdict.criteria_met)
            and verdict.confidence >= self.critic.confidence_threshold
        ):
            criteria_met = list(verdict.criteria_met)
        self._stash_critic_suggestions(verdict)
        return verdict, criteria_met
