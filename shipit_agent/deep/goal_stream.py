"""GoalAgent's streaming run."""

from __future__ import annotations


class _GoalStream:
    """GoalAgent's streaming run."""

    def stream(self):
        """Run the goal agent and yield events in real time.

        Example::

            for event in goal_agent.stream():
                print(f"[{event.type}] {event.message}")
        """
        from shipit_agent.core.models import AgentEvent

        yield AgentEvent(
            type="run_started",
            message=f"Goal: {self.goal.objective}",
            payload={
                "objective": self.goal.objective,
                "criteria": self.goal.success_criteria,
            },
        )

        yield AgentEvent(
            type="planning_started", message="Decomposing goal into sub-tasks"
        )
        subtasks = self._decompose()
        yield AgentEvent(
            type="planning_completed",
            message=f"Decomposed into {len(subtasks)} sub-tasks",
            payload={"subtasks": subtasks},
        )

        agent = self._build_agent()
        work_done: list[str] = []
        all_outputs: list[str] = []

        for step_num, task in enumerate(subtasks[: self.goal.max_steps], 1):
            yield AgentEvent(
                type="step_started",
                message=f"Step {step_num}/{len(subtasks)}: {task[:80]}",
                payload={"step": step_num, "task": task},
            )

            result = agent.run(task)
            work_done.append(result.output)
            all_outputs.append(result.output)

            # Yield the step output so the caller can see it
            yield AgentEvent(
                type="tool_completed",
                message=f"Step {step_num} output",
                payload={"step": step_num, "output": result.output},
            )

            yield AgentEvent(
                type="step_started",
                message=f"Evaluating progress after step {step_num}",
            )
            evaluation = self._evaluate(work_done)
            criteria_met = evaluation.get("criteria_met", [])
            yield AgentEvent(
                type="tool_completed",
                message=f"Criteria met: {criteria_met}",
                payload={
                    "criteria_met": criteria_met,
                    "all_done": evaluation.get("all_done", False),
                },
            )

            if evaluation.get("all_done"):
                final_output = "\n\n".join(all_outputs)
                yield AgentEvent(
                    type="run_completed",
                    message="Goal completed",
                    payload={
                        "status": "completed",
                        "steps": step_num,
                        "criteria_met": criteria_met,
                        "output": final_output,
                    },
                )
                return

        final_output = "\n\n".join(all_outputs)
        yield AgentEvent(
            type="run_completed",
            message="Goal finished (max steps reached)",
            payload={
                "status": "partial",
                "steps": len(work_done),
                "output": final_output,
            },
        )
