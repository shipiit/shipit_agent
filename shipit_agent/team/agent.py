from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TeamAgent:
    """An agent with a role in a team.

    Example::

        researcher = TeamAgent(
            name="researcher",
            role="Expert at finding information from the web",
            agent=Agent.with_builtins(llm=llm),
        )

        # Or create with builtins directly:
        researcher = TeamAgent.with_builtins(
            name="researcher",
            role="Expert at finding information",
            llm=llm,
        )
    """

    name: str
    role: str
    agent: Any
    capabilities: list[str] = field(default_factory=list)

    @classmethod
    def with_builtins(
        cls,
        *,
        name: str,
        role: str,
        llm: Any,
        mcps: list[Any] | None = None,
        capabilities: list[str] | None = None,
        **kwargs: Any,
    ) -> "TeamAgent":
        """Create a TeamAgent backed by an Agent with all built-in tools."""
        from shipit_agent.agent import Agent

        agent = Agent.with_builtins(
            llm=llm, prompt=f"You are {name}. {role}", mcps=mcps, **kwargs
        )
        return cls(name=name, role=role, agent=agent, capabilities=capabilities or [])
