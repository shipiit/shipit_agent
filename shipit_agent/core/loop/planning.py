"""Planning before acting: run the planner tool first when the router policy asks for a plan.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import Message, ToolCall
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.tools import ToolContext


class PlanningMixin:
    """Planning before acting: run the planner tool first when the router policy asks for a plan."""

    async def _run_planner_if_needed(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        user_prompt: str,
        base_prompt: str,
        shared_state: dict[str, Any],
        tool_runner: ToolRunner,
    ) -> None:
        planner = registry.get("plan_task")
        if (
            planner is None
            or not self.router_policy.auto_plan
            or not self.router_policy.should_plan(user_prompt)
        ):
            return
        self.emit(state, "planning_started", "Planner started", prompt=user_prompt)
        result = await tool_runner.run_tool_call_async(
            ToolCall(name=planner.name, arguments={"goal": user_prompt}),
            ToolContext(
                prompt=user_prompt,
                system_prompt=base_prompt,
                metadata=dict(self.metadata),
                state=shared_state,
                session_id=self.session_id,
            ),
        )
        state.tool_results.append(result)
        state.messages.append(
            Message(
                role="user",
                content=f"[Planner output]\n{result.output}",
                metadata={
                    "source": "planner",
                    "planner_tool": planner.name,
                    "internal": True,
                },
            )
        )
        self.emit(
            state, "planning_completed", "Planner completed", output=result.output
        )
