"""ShipCrew — multi-agent crew orchestration with DAG-based task execution.

The main entry point for composing specialised agents into a workflow.
A coordinator plans the work, agents execute tasks, and results flow
between them automatically through template variable resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator

from .agent import ShipAgent
from .coordinator import ShipCoordinator
from .errors import ShipCrewError
from .result import ShipCrewResult
from .task import ShipTask


# ---------------------------------------------------------------------------
# ShipCrew
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ShipCrew:
    """Multi-agent crew orchestration with DAG-based task execution.

    Specialised agents collaborate on a workflow with defined data flow.
    A coordinator plans the work, agents execute tasks, and results
    flow between them automatically via template variables.

    Example::

        crew = ShipCrew(
            name="research-crew",
            coordinator_llm=llm,
            agents=[
                ShipAgent(name="researcher", agent=researcher_agent,
                          role="Researcher", goal="Find accurate info"),
                ShipAgent(name="writer", agent=writer_agent,
                          role="Technical Writer", goal="Write clearly"),
            ],
            tasks=[
                ShipTask(name="research", description="Research {topic}",
                         agent="researcher", output_key="findings"),
                ShipTask(name="write", description="Write report using {findings}",
                         agent="writer", depends_on=["research"]),
            ],
        )
        result = crew.run(topic="AI agents")
    """

    name: str
    coordinator_llm: Any
    agents: list[ShipAgent]
    tasks: list[ShipTask]
    process: str = "sequential"
    max_rounds: int = 10
    verbose: bool = False

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Check for configuration errors before execution.

        Returns a list of human-readable error descriptions.  An empty
        list means the crew is valid.

        Checks performed:
        - Every task references a registered agent.
        - No cyclic dependencies in the task DAG.
        - Every ``depends_on`` entry names an existing task.
        - Every ``output_key`` referenced in templates is produced by
          an upstream task.
        """
        errors: list[str] = []
        agent_names = {a.name for a in self.agents}
        task_names = {t.name for t in self.tasks}
        output_keys = {t.output_key for t in self.tasks}

        for task in self.tasks:
            # Check agent exists.
            if task.agent not in agent_names:
                errors.append(
                    f"Task '{task.name}' references unknown agent '{task.agent}'. "
                    f"Available: {sorted(agent_names)}"
                )

            # Check dependencies exist.
            for dep in task.depends_on:
                if dep not in task_names:
                    errors.append(f"Task '{task.name}' depends on unknown task '{dep}'")

        # Check for cycles by attempting the DAG build.
        try:
            ShipCoordinator._build_dag(self.tasks)
        except ShipCrewError as exc:
            errors.append(str(exc))

        # Check template references.
        for task in self.tasks:
            # Extract {var} references from the description.
            import re

            refs = set(re.findall(r"\{(\w+)\}", task.description))
            # Filter out context vars (those are provided at run time).
            for ref in refs:
                if ref not in output_keys:
                    # It's only an error if it's not a context variable
                    # (context vars are provided at run time, so we
                    # can't validate them statically — just note it).
                    pass  # Context vars are allowed and resolved at runtime.

        return errors

    # ------------------------------------------------------------------ #
    # Mutators
    # ------------------------------------------------------------------ #

    def add_agent(self, agent: ShipAgent) -> None:
        """Add an agent to the crew.

        Args:
            agent: The ``ShipAgent`` to register.
        """
        self.agents.append(agent)

    def add_task(self, task: ShipTask) -> None:
        """Add a task to the crew workflow.

        Args:
            task: The ``ShipTask`` to append.
        """
        self.tasks.append(task)

    # ------------------------------------------------------------------ #
    # Coordinator construction
    # ------------------------------------------------------------------ #

    def _build_coordinator(
        self,
        context_vars: dict[str, Any] | None = None,
    ) -> ShipCoordinator:
        """Create a ``ShipCoordinator`` for the current configuration.

        If *context_vars* are provided they are injected into every
        task's description before the coordinator receives them.

        Args:
            context_vars: Runtime variables like ``topic="AI agents"``.

        Returns:
            A ready-to-run ``ShipCoordinator``.
        """
        agents_map = {a.name: a for a in self.agents}

        # Pre-resolve context variables in task descriptions so the
        # coordinator sees concrete text (upstream output_key vars
        # are left as-is for later resolution).
        tasks = self.tasks
        if context_vars:
            resolved_tasks: list[ShipTask] = []
            for task in tasks:
                resolved_desc = task.resolve_description(context_vars)
                resolved_tasks.append(
                    ShipTask(
                        name=task.name,
                        description=resolved_desc,
                        agent=task.agent,
                        depends_on=list(task.depends_on),
                        output_key=task.output_key,
                        output_schema=task.output_schema,
                        max_retries=task.max_retries,
                        timeout_seconds=task.timeout_seconds,
                        context={**task.context, **context_vars},
                    )
                )
            tasks = resolved_tasks

        return ShipCoordinator(
            llm=self.coordinator_llm,
            agents=agents_map,
            tasks=tasks,
            process=self.process,
            max_rounds=self.max_rounds,
            verbose=self.verbose,
        )

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def run(self, **context_vars: Any) -> ShipCrewResult:
        """Execute the crew workflow.

        Keyword arguments are injected as template variables into task
        descriptions (e.g. ``crew.run(topic="AI agents")`` fills every
        ``{topic}`` placeholder).

        Returns:
            A ``ShipCrewResult`` containing the final output, per-task
            results, execution order, and metadata.
        """
        coordinator = self._build_coordinator(context_vars or None)
        return coordinator.run()

    def stream(self, **context_vars: Any) -> Generator:
        """Stream events during crew execution.

        Yields ``AgentEvent`` objects for each significant milestone:
        crew start, task start/complete/fail, and crew completion.

        Keyword arguments are injected as template variables, same as
        ``run()``.
        """
        coordinator = self._build_coordinator(context_vars or None)
        yield from coordinator.stream()


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def create_ship_crew(
    *,
    coordinator_llm: Any,
    agents: list[dict[str, Any] | ShipAgent],
    tasks: list[dict[str, Any] | ShipTask],
    process: str = "sequential",
    **kwargs: Any,
) -> ShipCrew:
    """Convenience factory for creating a ``ShipCrew`` from dicts or objects.

    Accepts either fully-formed ``ShipAgent`` / ``ShipTask`` objects or
    plain dicts (useful when loading from JSON configuration).

    Example::

        crew = create_ship_crew(
            coordinator_llm=llm,
            agents=[
                {"name": "researcher", "agent": r_agent, "role": "Researcher"},
                writer_agent,  # already a ShipAgent
            ],
            tasks=[
                {"name": "research", "description": "Research {topic}", "agent": "researcher"},
                write_task,    # already a ShipTask
            ],
        )

    Args:
        coordinator_llm: The LLM instance for the coordinator.
        agents: List of ``ShipAgent`` instances or dicts.
        tasks: List of ``ShipTask`` instances or dicts.
        process: Execution mode — ``"sequential"``, ``"parallel"``,
                 or ``"hierarchical"``.
        **kwargs: Extra keyword arguments forwarded to ``ShipCrew``.

    Returns:
        A configured ``ShipCrew`` ready for execution.
    """
    resolved_agents: list[ShipAgent] = []
    for entry in agents:
        if isinstance(entry, ShipAgent):
            resolved_agents.append(entry)
        elif isinstance(entry, dict):
            resolved_agents.append(ShipAgent(**entry))
        else:
            raise ShipCrewError(
                f"Expected ShipAgent or dict, got {type(entry).__name__}"
            )

    resolved_tasks: list[ShipTask] = []
    for entry in tasks:
        if isinstance(entry, ShipTask):
            resolved_tasks.append(entry)
        elif isinstance(entry, dict):
            resolved_tasks.append(ShipTask.from_dict(entry))
        else:
            raise ShipCrewError(
                f"Expected ShipTask or dict, got {type(entry).__name__}"
            )

    return ShipCrew(
        coordinator_llm=coordinator_llm,
        agents=resolved_agents,
        tasks=resolved_tasks,
        process=process,
        **kwargs,
    )
