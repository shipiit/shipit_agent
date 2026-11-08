"""Supervisor's streaming run."""

from __future__ import annotations

from .supervisor_types import Delegation


class _SupervisorStream:
    """Supervisor's streaming run."""

    def stream(self, task: str):
        """Run the supervisor and yield events in real time.

        Example::

            for event in supervisor.stream("Analyze data and write report"):
                print(f"[{event.payload.get('worker', 'supervisor')}] {event.message}")
        """
        from shipit_agent.core.models import AgentEvent

        yield AgentEvent(
            type="run_started",
            message=f"Supervisor: {task[:80]}",
            payload={"task": task, "workers": list(self.workers.keys())},
        )

        delegations: list[Delegation] = []

        for round_num in range(1, self.max_delegations + 1):
            yield AgentEvent(
                type="planning_started",
                message=f"Round {round_num}: Supervisor deciding next step",
            )
            decision = self._ask_supervisor(task, delegations)
            action = decision.get("action", "done")

            if action == "done":
                final = decision.get("final_answer", "")
                if not final and delegations:
                    final = delegations[-1].output
                yield AgentEvent(
                    type="run_completed",
                    message="Supervisor: task complete",
                    payload={"output": final[:300], "rounds": round_num},
                )
                return

            worker_name = decision.get("worker", "")
            worker_task = decision.get("task", task)
            worker = self.workers.get(worker_name)

            if worker is None:
                yield AgentEvent(
                    type="tool_failed",
                    message=f"Worker '{worker_name}' not found",
                    payload={"worker": worker_name},
                )
                delegations.append(
                    Delegation(
                        round=round_num,
                        worker=worker_name,
                        task=worker_task,
                        output=f"Error: worker '{worker_name}' not found",
                    )
                )
                continue

            yield AgentEvent(
                type="tool_called",
                message=f"Delegating to {worker_name}: {worker_task[:80]}",
                payload={"worker": worker_name, "task": worker_task},
            )

            result = worker.agent.run(worker_task)
            delegations.append(
                Delegation(
                    round=round_num,
                    worker=worker_name,
                    task=worker_task,
                    output=result.output,
                    approved=(action != "revise"),
                )
            )

            yield AgentEvent(
                type="tool_completed",
                message=f"{worker_name} finished",
                payload={"worker": worker_name, "output": result.output},
            )

        yield AgentEvent(
            type="run_completed",
            message="Supervisor: max rounds reached",
            payload={"rounds": self.max_delegations},
        )
