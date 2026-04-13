"""ShipCoordinator — orchestrates task execution across agents in a ShipCrew.

Supports three process modes:
- **sequential**: tasks execute one at a time in topological order.
- **parallel**: independent tasks within each DAG layer run concurrently
  using ``ThreadPoolExecutor``.
- **hierarchical**: a coordinator LLM dynamically assigns tasks and
  reviews outputs, adapting the plan as results come in.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generator

from .agent import ShipAgent
from .errors import (
    CyclicDependencyError,
    MissingAgentError,
    ShipCrewError,
    TaskTimeoutError,
)
from .result import ShipCrewResult
from .task import ShipTask


# ---------------------------------------------------------------------------
# LLM prompt for hierarchical mode
# ---------------------------------------------------------------------------

_HIERARCHICAL_PROMPT = """\
You are a crew coordinator managing a team of specialised agents.
Review the current state and decide the next action.

## Available Agents
{agents}

## Remaining Tasks
{tasks}

## Completed Work
{completed}

Respond with JSON only. Choose ONE action:
- Assign a task: {{"action": "assign", "task": "<task_name>", "agent": "<agent_name>", "instructions": "<detailed prompt>"}}
- Request revision: {{"action": "revise", "task": "<task_name>", "agent": "<agent_name>", "feedback": "<what to improve>"}}
- Mark done: {{"action": "done", "summary": "<final synthesised output>"}}
"""


# ---------------------------------------------------------------------------
# ShipCoordinator
# ---------------------------------------------------------------------------

class ShipCoordinator:
    """Orchestrates task execution across agents in a ShipCrew.

    The coordinator builds a DAG from task dependencies, resolves a
    topological execution order (optionally parallelised), and drives
    each task through the assigned agent.  In hierarchical mode an LLM
    plans and reviews dynamically.
    """

    def __init__(
        self,
        llm: Any,
        agents: dict[str, ShipAgent],
        tasks: list[ShipTask],
        process: str = "sequential",
        max_rounds: int = 10,
        verbose: bool = False,
    ) -> None:
        self.llm = llm
        self.agents = agents
        self.tasks = {t.name: t for t in tasks}
        self.process = process
        self.max_rounds = max_rounds
        self.verbose = verbose

        # Pre-validate agent assignments.
        self._validate_agents(tasks, agents)

        # Build the DAG and resolve execution layers.
        self._adjacency: dict[str, list[str]] = self._build_dag(tasks)
        self._layers: list[list[ShipTask]] = self._resolve_execution_order()

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_agents(
        tasks: list[ShipTask], agents: dict[str, ShipAgent]
    ) -> None:
        """Raise ``MissingAgentError`` if any task references an unknown agent."""
        for task in tasks:
            if task.agent not in agents:
                raise MissingAgentError(
                    f"Task '{task.name}' references agent '{task.agent}' "
                    f"which is not registered. Available: {list(agents)}"
                )

    # ------------------------------------------------------------------ #
    # DAG construction (Kahn's algorithm)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_dag(tasks: list[ShipTask]) -> dict[str, list[str]]:
        """Build an adjacency list from task dependencies.

        Returns a mapping of ``task_name -> [downstream_task_names]``.
        Raises ``CyclicDependencyError`` if the graph contains a cycle.
        """
        task_names = {t.name for t in tasks}
        adjacency: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {t.name: 0 for t in tasks}

        for task in tasks:
            for dep in task.depends_on:
                if dep not in task_names:
                    raise ShipCrewError(
                        f"Task '{task.name}' depends on unknown task '{dep}'"
                    )
                adjacency[dep].append(task.name)
                in_degree[task.name] += 1

        # Kahn's algorithm — detect cycles.
        queue: deque[str] = deque(
            name for name, deg in in_degree.items() if deg == 0
        )
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbour in adjacency[node]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if visited != len(tasks):
            # Some tasks were never reachable — there's a cycle.
            stuck = [n for n, d in in_degree.items() if d > 0]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among tasks: {stuck}"
            )

        return dict(adjacency)

    def _resolve_execution_order(self) -> list[list[ShipTask]]:
        """Topological sort into layers of parallelisable tasks.

        Each layer contains tasks whose dependencies are all satisfied
        by earlier layers.  Within a layer, tasks are independent and
        can safely run concurrently.
        """
        in_degree: dict[str, int] = {name: 0 for name in self.tasks}
        for task in self.tasks.values():
            for dep in task.depends_on:
                in_degree[task.name] += 1

        layers: list[list[ShipTask]] = []
        ready: list[str] = [n for n, d in in_degree.items() if d == 0]

        while ready:
            layer = [self.tasks[name] for name in sorted(ready)]
            layers.append(layer)

            next_ready: list[str] = []
            for task in layer:
                for downstream in self._adjacency.get(task.name, []):
                    in_degree[downstream] -= 1
                    if in_degree[downstream] == 0:
                        next_ready.append(downstream)
            ready = next_ready

        return layers

    # ------------------------------------------------------------------ #
    # Task execution
    # ------------------------------------------------------------------ #

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
            context_str = "\n".join(
                f"- {k}: {v}" for k, v in task.context.items()
            )
            prompt = f"{prompt}\n\nAdditional context:\n{context_str}"

        last_error: Exception | None = None
        for attempt in range(1, task.max_retries + 1):
            try:
                start = time.monotonic()
                result = agent.run(prompt)
                elapsed = time.monotonic() - start

                if elapsed > task.timeout_seconds:
                    raise TaskTimeoutError(
                        f"Task '{task.name}' took {elapsed:.1f}s "
                        f"(limit: {task.timeout_seconds}s)"
                    )

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
        raise ShipCrewError(f"Task '{task.name}' failed: {last_error}")  # pragma: no cover

    # ------------------------------------------------------------------ #
    # Process modes
    # ------------------------------------------------------------------ #

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
                pool.submit(
                    self._execute_task, task, dict(outputs), agents
                ): task
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
        from shipit_agent.models import Message

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
                "\n".join(
                    f"- {k}: {v[:300]}" for k, v in outputs.items()
                )
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

            instructions = decision.get(
                "instructions", decision.get("feedback", "")
            )
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

    # ------------------------------------------------------------------ #
    # JSON parsing helper (matches supervisor.py pattern)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Extract the first JSON object from an LLM response."""
        text = text.strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"action": "done", "summary": text}

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def run(self) -> ShipCrewResult:
        """Execute all tasks and return a ``ShipCrewResult``."""
        start_time = time.monotonic()
        execution_order: list[str] = []
        failed: list[str] = []

        try:
            if self.process == "hierarchical":
                outputs = self._execute_hierarchical(self.agents)
                execution_order = list(outputs.keys())
            elif self.process == "parallel":
                outputs: dict[str, str] = {}
                for layer in self._layers:
                    layer_outputs = self._execute_parallel(
                        layer, self.agents, outputs
                    )
                    outputs.update(layer_outputs)
                    execution_order.extend(t.name for t in layer)
            else:
                # Default: sequential.
                outputs = self._execute_sequential(self.agents)
                execution_order = [t.name for layer in self._layers for t in layer]
        except ShipCrewError as exc:
            # Partial failure — collect what we have.
            elapsed = time.monotonic() - start_time
            return ShipCrewResult(
                output=f"Crew execution failed: {exc}",
                task_results={},
                execution_order=execution_order,
                total_tasks=len(self.tasks),
                failed_tasks=[str(exc)],
                metadata={"elapsed_seconds": round(elapsed, 2)},
            )

        elapsed = time.monotonic() - start_time

        # The final output is the last task's result (or the summary
        # from hierarchical mode).
        if "_summary" in outputs:
            final_output = outputs.pop("_summary")
        elif outputs:
            # Use the output of the last task in topological order.
            last_key = list(outputs.keys())[-1]
            final_output = outputs[last_key]
        else:
            final_output = ""

        return ShipCrewResult(
            output=final_output,
            task_results=outputs,
            execution_order=execution_order,
            total_tasks=len(self.tasks),
            failed_tasks=failed,
            metadata={"elapsed_seconds": round(elapsed, 2)},
        )

    def stream(self) -> Generator:
        """Execute all tasks, yielding ``AgentEvent`` objects.

        Emits events for: ``crew_started``, ``task_started``,
        ``task_completed``, ``task_failed``, ``crew_completed``.
        """
        from shipit_agent.models import AgentEvent

        yield AgentEvent(
            type="run_started",
            message=f"Crew started ({self.process} mode, {len(self.tasks)} tasks)",
            payload={
                "process": self.process,
                "tasks": list(self.tasks.keys()),
                "agents": list(self.agents.keys()),
            },
        )

        start_time = time.monotonic()
        outputs: dict[str, str] = {}
        execution_order: list[str] = []
        failed: list[str] = []

        for layer in self._layers:
            for task in layer:
                yield AgentEvent(
                    type="tool_called",
                    message=f"Task '{task.name}' started (agent: {task.agent})",
                    payload={
                        "task": task.name,
                        "agent": task.agent,
                        "description": task.resolve_description(outputs)[:200],
                    },
                )

                try:
                    output = self._execute_task(task, outputs, self.agents)
                    outputs[task.output_key] = output
                    execution_order.append(task.name)

                    yield AgentEvent(
                        type="tool_completed",
                        message=f"Task '{task.name}' completed",
                        payload={
                            "task": task.name,
                            "output_key": task.output_key,
                            "output": output[:500],
                        },
                    )

                except (ShipCrewError, Exception) as exc:
                    failed.append(task.name)
                    execution_order.append(task.name)

                    yield AgentEvent(
                        type="tool_failed",
                        message=f"Task '{task.name}' failed: {exc}",
                        payload={"task": task.name, "error": str(exc)},
                    )

        elapsed = time.monotonic() - start_time

        # Determine final output.
        if outputs:
            last_key = list(outputs.keys())[-1]
            final_output = outputs[last_key]
        else:
            final_output = ""

        yield AgentEvent(
            type="run_completed",
            message="Crew completed",
            payload={
                "output": final_output[:500],
                "execution_order": execution_order,
                "failed_tasks": failed,
                "elapsed_seconds": round(elapsed, 2),
            },
        )
