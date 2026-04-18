"""ShipAgent — a named, persona-driven agent within a ShipCrew.

Wraps any shipit_agent ``Agent`` instance with identity metadata
(role, goal, backstory) so the coordinator can reason about each
agent's strengths when planning work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass(slots=True)
class ShipAgent:
    """A named agent within a ShipCrew.

    Wraps any shipit_agent Agent with a name, role, goal, and backstory
    for persona-driven behavior within the crew.

    Example::

        researcher = ShipAgent(
            name="researcher",
            agent=Agent.with_builtins(llm=llm, prompt="You are a researcher."),
            role="Senior Researcher",
            goal="Find comprehensive, accurate information",
            backstory="You have 20 years of research experience.",
            capabilities=["web search", "summarisation"],
        )
        result = researcher.run("Find information about quantum computing")
    """

    name: str
    agent: Any
    role: str = ""
    goal: str = ""
    backstory: str = ""
    capabilities: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Execution — delegates to the underlying agent
    # ------------------------------------------------------------------ #

    def run(self, prompt: str) -> Any:
        """Execute a task and return an ``AgentResult``.

        Builds a persona-enhanced prompt and delegates to the
        wrapped agent's ``run`` method.

        Args:
            prompt: The task description to execute.

        Returns:
            An ``AgentResult`` from the underlying agent.
        """
        enriched = self._build_prompt(prompt)
        return self.agent.run(enriched)

    def stream(self, prompt: str) -> Generator:
        """Execute a task and yield ``AgentEvent`` objects.

        Args:
            prompt: The task description to execute.

        Yields:
            ``AgentEvent`` instances from the underlying agent.
        """
        enriched = self._build_prompt(prompt)
        yield from self.agent.stream(enriched)

    # ------------------------------------------------------------------ #
    # Prompt enrichment
    # ------------------------------------------------------------------ #

    def _build_prompt(self, prompt: str) -> str:
        """Prepend persona context to the raw task prompt.

        Keeps the persona brief so it doesn't overwhelm the actual
        task instructions.
        """
        parts: list[str] = []
        if self.role:
            parts.append(f"[Role: {self.role}]")
        if self.goal:
            parts.append(f"[Goal: {self.goal}]")
        if self.backstory:
            parts.append(f"[Background: {self.backstory}]")
        if parts:
            parts.append("")  # blank line before the actual prompt
        parts.append(prompt)
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Factory — build from the AgentRegistry
    # ------------------------------------------------------------------ #

    @classmethod
    def from_registry(
        cls,
        agent_id: str,
        llm: Any,
        *,
        mcps: list[Any] | None = None,
        **overrides: Any,
    ) -> ShipAgent:
        """Create a ``ShipAgent`` from a registered ``AgentDefinition``.

        Looks up the agent definition by *agent_id* in the default
        registry, builds a live ``Agent`` with built-in tools, and
        wraps it in a ``ShipAgent`` with the definition's persona.

        Args:
            agent_id: The identifier of the agent in the registry
                      (e.g. ``"security-auditor"``).
            llm: The LLM instance to power the agent.
            mcps: Optional list of MCP servers to attach.
            **overrides: Override any ``ShipAgent`` field (e.g.
                         ``role="Custom Role"``).

        Returns:
            A fully configured ``ShipAgent``.

        Raises:
            KeyError: If *agent_id* is not found in the registry.
        """
        from shipit_agent.agent import Agent
        from shipit_agent.agents import AgentRegistry

        registry = AgentRegistry.default()
        definition = registry.get(agent_id)
        if definition is None:
            raise KeyError(f"Unknown agent registry id: {agent_id}")

        agent = Agent.with_builtins(
            llm=llm,
            prompt=definition.system_prompt(),
            mcps=mcps,
        )

        return cls(
            name=overrides.get("name", definition.name or agent_id),
            agent=agent,
            role=overrides.get("role", definition.role),
            goal=overrides.get("goal", definition.goal),
            backstory=overrides.get("backstory", definition.backstory),
            capabilities=overrides.get("capabilities", list(definition.tools)),
        )
