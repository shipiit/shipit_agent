"""AgentRegistry — load, search, and manage collections of prebuilt AgentDefinitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .definition import AgentDefinition


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AgentRegistry:
    """An indexed collection of :class:`AgentDefinition` objects.

    Registries can be loaded from a single ``agents.json`` file, from a
    directory of individual JSON files, or merged together so that
    project-level definitions override built-in ones.

    Example::

        registry = AgentRegistry.default()
        agent = registry.get("security-auditor")
        print(agent.system_prompt())
    """

    def __init__(self, agents: list[AgentDefinition] | None = None) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        for agent in agents or []:
            self._agents[agent.id] = agent

    # --------------------------------------------------------------------- #
    # Loaders
    # --------------------------------------------------------------------- #

    @classmethod
    def load(cls, path: str | Path) -> AgentRegistry:
        """Load a registry from a single JSON file.

        The file should contain a top-level JSON array of agent objects.
        """
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data: list[dict[str, Any]] = json.load(fh)

        agents = [AgentDefinition.from_dict(entry) for entry in data]
        return cls(agents)

    @classmethod
    def from_directory(cls, path: str | Path) -> AgentRegistry:
        """Load a registry from a directory of individual ``.json`` files.

        Each file should contain a single agent object (a JSON dict).
        """
        path = Path(path)
        agents: list[AgentDefinition] = []
        for json_file in sorted(path.glob("*.json")):
            with json_file.open("r", encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
            agents.append(AgentDefinition.from_dict(data))
        return cls(agents)

    @classmethod
    def default(cls) -> AgentRegistry:
        """Load the built-in ``agents.json`` shipped with the package."""
        builtin = Path(__file__).parent / "agents.json"
        return cls.load(builtin)

    # --------------------------------------------------------------------- #
    # Lookup helpers
    # --------------------------------------------------------------------- #

    def get(self, agent_id: str) -> AgentDefinition | None:
        """Return an agent by its unique id, or ``None`` if not found."""
        return self._agents.get(agent_id)

    def search(self, query: str) -> list[AgentDefinition]:
        """Fuzzy search agents by matching *query* against name, role, goal, and tags.

        Returns agents sorted by relevance (number of matching tokens).
        """
        tokens = query.lower().split()
        scored: list[tuple[int, AgentDefinition]] = []

        for agent in self._agents.values():
            haystack = " ".join(
                [
                    agent.id,
                    agent.name,
                    agent.role,
                    agent.goal,
                    agent.category,
                    " ".join(agent.tags),
                ]
            ).lower()

            hits = sum(1 for t in tokens if t in haystack)
            if hits > 0:
                scored.append((hits, agent))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [agent for _, agent in scored]

    def list_by_category(self, category: str) -> list[AgentDefinition]:
        """Return all agents whose category matches (case-insensitive)."""
        cat = category.lower()
        return [a for a in self._agents.values() if a.category.lower() == cat]

    def list_all(self) -> list[AgentDefinition]:
        """Return every registered agent, sorted by id."""
        return sorted(self._agents.values(), key=lambda a: a.id)

    def all(self) -> list[AgentDefinition]:
        """Alias for :meth:`list_all` — matches the common ``.all()`` idiom."""
        return self.list_all()

    def categories(self) -> list[str]:
        """Return a sorted list of unique category names."""
        return sorted({a.category for a in self._agents.values() if a.category})

    # --------------------------------------------------------------------- #
    # Composition
    # --------------------------------------------------------------------- #

    def merge(self, other: AgentRegistry) -> AgentRegistry:
        """Merge two registries; agents in *other* override same-id agents in *self*."""
        combined = dict(self._agents)
        combined.update(other._agents)
        return AgentRegistry(list(combined.values()))

    # --------------------------------------------------------------------- #
    # Dunder helpers
    # --------------------------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def __repr__(self) -> str:
        return f"AgentRegistry(agents={len(self._agents)})"
