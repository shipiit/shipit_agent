"""Crew planning: agent validation, the task DAG and execution order."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

from .agent import ShipAgent
from .errors import (
    CyclicDependencyError,
    MissingAgentError,
    ShipCrewError,
)
from .task import ShipTask


class _CrewPlanning:
    """Crew planning: agent validation, the task DAG and execution order."""

    @staticmethod
    def _validate_agents(tasks: list[ShipTask], agents: dict[str, ShipAgent]) -> None:
        """Raise ``MissingAgentError`` if any task references an unknown agent."""
        for task in tasks:
            if task.agent not in agents:
                raise MissingAgentError(
                    f"Task '{task.name}' references agent '{task.agent}' "
                    f"which is not registered. Available: {list(agents)}"
                )

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
        queue: deque[str] = deque(name for name, deg in in_degree.items() if deg == 0)
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
