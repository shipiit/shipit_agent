"""ShipCoordinator — orchestrates task execution across agents in a ShipCrew.

Supports three process modes:
- **sequential**: tasks execute one at a time in topological order.
- **parallel**: independent tasks within each DAG layer run concurrently
  using ``ThreadPoolExecutor``.
- **hierarchical**: a coordinator LLM dynamically assigns tasks and
  reviews outputs, adapting the plan as results come in.
"""

from __future__ import annotations

import time
from typing import Any, Generator

from .agent import ShipAgent
from .errors import (
    ShipCrewError,
)
from .execution import _CrewExecution
from .planning import _CrewPlanning
from .result import ShipCrewResult
from .task import ShipTask

# ---------------------------------------------------------------------------
# LLM prompt for hierarchical mode


# ---------------------------------------------------------------------------
# ShipCoordinator
# ---------------------------------------------------------------------------


class ShipCoordinator(_CrewPlanning, _CrewExecution):
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
    # DAG construction (Kahn's algorithm)

    # ------------------------------------------------------------------ #
    # Task execution

    # ------------------------------------------------------------------ #
    # Process modes

    # ------------------------------------------------------------------ #
    # JSON parsing helper (matches supervisor.py pattern)

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
                    layer_outputs = self._execute_parallel(layer, self.agents, outputs)
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
        from shipit_agent.core.models import AgentEvent

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
                            # Emit the full output — truncating here cripples
                            # UIs that show each task's result, and the
                            # downstream consumer can truncate as needed.
                            "output": output,
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
                "output": final_output,
                "execution_order": execution_order,
                "failed_tasks": failed,
                "elapsed_seconds": round(elapsed, 2),
            },
        )
