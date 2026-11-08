"""Crew execution: one task, and sequential, parallel and hierarchical runs."""

from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from concurrent.futures import (
    TimeoutError as FutureTimeoutError,
)

from .agent import ShipAgent
from .errors import (
    ShipCrewError,
    TaskTimeoutError,
)
from .prompts import _HIERARCHICAL_PROMPT
from .task import ShipTask


class _CrewExecution:
    """Crew execution: one task, and sequential, parallel and hierarchical runs."""

    def _execute_task(
        self,
        task: ShipTask,
        outputs: dict[str, str],
        agents: dict[str, ShipAgent],
    ) -> str:
        """Execute a single task through its assigned agent.

        Resolves template variables, retries on failure, and enforces
        the per-task timeout.

        Returns the task output as a string.
        """
        agent = agents[task.agent]
        prompt = task.resolve_description(outputs)

        # Merge any extra context into the prompt.
        if task.context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in task.context.items())
            prompt = f"{prompt}\n\nAdditional context:\n{context_str}"

        last_error: Exception | None = None
        for attempt in range(1, task.max_retries + 1):
            try:
                # Run the agent under a future so the timeout actually preempts
                # (stops waiting) instead of only being measured after the fact.
                # Python can't kill the worker thread, so a timed-out run keeps
                # finishing in the background — but the crew no longer hangs on
                # it. shutdown(wait=False) avoids blocking on that runaway run.
                pool = ThreadPoolExecutor(max_workers=1)
                future = pool.submit(agent.run, prompt)
                try:
                    result = future.result(timeout=task.timeout_seconds)
                except FutureTimeoutError:
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise TaskTimeoutError(
                        f"Task '{task.name}' exceeded the "
                        f"{task.timeout_seconds}s limit"
                    ) from None
                pool.shutdown(wait=False)

                return result.output

            except TaskTimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < task.max_retries:
                    continue
                raise ShipCrewError(
                    f"Task '{task.name}' failed after {task.max_retries} "
                    f"attempt(s): {last_error}"
                ) from last_error

        # Unreachable, but keeps type checkers happy.
        raise ShipCrewError(
            f"Task '{task.name}' failed: {last_error}"
        )  # pragma: no cover

    def _execute_sequential(
        self,
        agents: dict[str, ShipAgent],
    ) -> dict[str, str]:
        """Run all tasks one at a time in topological order."""
        outputs: dict[str, str] = {}
        for layer in self._layers:
            for task in layer:
                output = self._execute_task(task, outputs, agents)
                outputs[task.output_key] = output
        return outputs

    def _execute_parallel(
        self,
        task_layer: list[ShipTask],
        agents: dict[str, ShipAgent],
        outputs: dict[str, str],
    ) -> dict[str, str]:
        """Run a single layer of independent tasks concurrently.

        Uses ``ThreadPoolExecutor`` to fan out work.  Results are
        collected once all tasks in the layer complete.
        """
        layer_outputs: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(task_layer)) as pool:
            future_to_task = {
                pool.submit(self._execute_task, task, dict(outputs), agents): task
                for task in task_layer
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                layer_outputs[task.output_key] = future.result()

        return layer_outputs

    def _execute_hierarchical(
        self,
        agents: dict[str, ShipAgent],
    ) -> dict[str, str]:
        """LLM-driven dynamic task assignment and review.

        The coordinator LLM decides which task to assign next and to
        which agent, reviews outputs, and can request revisions
        before moving on.
        """
        from shipit_agent.core.models import Message

        outputs: dict[str, str] = {}
        remaining = set(self.tasks.keys())

        for _ in range(self.max_rounds):
            if not remaining:
                break

            # Build the LLM prompt with current state.
            agents_desc = "\n".join(
                f"- {a.name}: {a.role}"
                + (f" [{', '.join(a.capabilities)}]" if a.capabilities else "")
                for a in agents.values()
            )
            tasks_desc = "\n".join(
                f"- {self.tasks[n].name}: {self.tasks[n].description}"
                for n in remaining
            )
            completed_desc = (
                "\n".join(f"- {k}: {v[:300]}" for k, v in outputs.items())
                if outputs
                else "(None yet)"
            )

            prompt = _HIERARCHICAL_PROMPT.format(
                agents=agents_desc,
                tasks=tasks_desc,
                completed=completed_desc,
            )

            response = self.llm.complete(
                messages=[Message(role="user", content=prompt)]
            )
            decision = self._parse_json(response.content)

            action = decision.get("action", "done")

            if action == "done":
                # LLM decided we're finished — store any summary.
                if "summary" in decision:
                    outputs["_summary"] = decision["summary"]
                break

            task_name = decision.get("task", "")
            task = self.tasks.get(task_name)

            if task is None:
                # LLM hallucinated a task name — skip this round.
                continue

            agent_name = decision.get("agent", task.agent)
            agent = agents.get(agent_name)
            if agent is None:
                agent = agents[task.agent]

            instructions = decision.get("instructions", decision.get("feedback", ""))
            if instructions:
                combined_outputs = {**outputs, "_instructions": instructions}
            else:
                combined_outputs = outputs

            try:
                output = self._execute_task(task, combined_outputs, agents)
                outputs[task.output_key] = output
                remaining.discard(task_name)
            except ShipCrewError:
                # Record the failure but keep going.
                outputs[task.output_key] = f"[FAILED] {task_name}"
                remaining.discard(task_name)

        return outputs
