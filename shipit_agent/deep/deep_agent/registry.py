"""DeepAgent accessors and the add_* methods for tools, skills, MCP servers and sub-agents."""

from __future__ import annotations

from typing import Any

from shipit_agent.skills import Skill

from .delegation import AgentDelegationTool


class _DeepAgentRegistry:
    """DeepAgent accessors and the add_* methods for tools, skills, MCP servers and sub-agents."""

    @property
    def agent(self) -> Any:
        """Return the underlying :class:`shipit_agent.Agent`."""
        return self._agent

    @property
    def tools(self) -> list[Any]:
        return self._agent.tools

    @property
    def skills_catalog(self) -> list[Skill]:
        return self._agent.available_skills()

    def search_skills(self, query: str) -> list[Skill]:
        return self._agent.search_skills(query)

    def add_skill(self, skill: str | Skill) -> Skill:
        added = self._agent.add_skill(skill)
        self.skills = list(self._agent.skills)
        return added

    @property
    def delegation_tool(self) -> AgentDelegationTool | None:
        """Return the active :class:`AgentDelegationTool`, if any."""
        for tool in self._agent.tools:
            if isinstance(tool, AgentDelegationTool):
                return tool
        return None

    @property
    def sub_agents(self) -> dict[str, Any]:
        """Return the dict of named sub-agents wired through ``agents=``."""
        delegate = self.delegation_tool
        return dict(delegate.agents) if delegate is not None else {}

    def add_tool(self, tool: Any) -> None:
        existing = {getattr(t, "name", None) for t in self._agent.tools}
        if getattr(tool, "name", None) not in existing:
            self._agent.tools.append(tool)

    def add_mcp(self, mcp: Any) -> None:
        if mcp not in self._agent.mcps:
            self._agent.mcps.append(mcp)

    def add_sub_agent(self, name: str, agent: Any) -> None:
        """Register a new sub-agent at runtime.

        If a delegation tool is already wired, the agent is added to it.
        Otherwise a fresh delegation tool is created and appended to the
        underlying agent's tool list.
        """
        delegate = self.delegation_tool
        if delegate is None:
            delegate = AgentDelegationTool(agents={name: agent})
            self._agent.tools.append(delegate)
            return
        delegate.add(name, agent)
