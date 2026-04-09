from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.mcp import MCPServer
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.tools import Tool
from shipit_agent.tracing import TraceStore


@dataclass(slots=True)
class AgentProfile:
    name: str
    prompt: str = DEFAULT_AGENT_PROMPT
    description: str = ""
    tools: list[Tool] = field(default_factory=list)
    mcps: list[MCPServer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 4
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)
    trace_store: TraceStore | None = None


class AgentProfileBuilder:
    def __init__(self, name: str):
        self._name = name
        self._prompt = DEFAULT_AGENT_PROMPT
        self._description = ""
        self._tools: list[Tool] = []
        self._mcps: list[MCPServer] = []
        self._metadata: dict[str, Any] = {}
        self._max_iterations = 4
        self._retry_policy = RetryPolicy()
        self._router_policy = RouterPolicy()
        self._trace_store: TraceStore | None = None

    def prompt(self, value: str) -> "AgentProfileBuilder":
        self._prompt = value
        return self

    def description(self, value: str) -> "AgentProfileBuilder":
        self._description = value
        return self

    def tool(self, value: Tool) -> "AgentProfileBuilder":
        self._tools.append(value)
        return self

    def tools(self, values: list[Tool]) -> "AgentProfileBuilder":
        self._tools.extend(values)
        return self

    def mcp(self, value: MCPServer) -> "AgentProfileBuilder":
        self._mcps.append(value)
        return self

    def mcps(self, values: list[MCPServer]) -> "AgentProfileBuilder":
        self._mcps.extend(values)
        return self

    def metadata(self, **kwargs: Any) -> "AgentProfileBuilder":
        self._metadata.update(kwargs)
        return self

    def max_iterations(self, value: int) -> "AgentProfileBuilder":
        self._max_iterations = value
        return self

    def retry_policy(self, value: RetryPolicy) -> "AgentProfileBuilder":
        self._retry_policy = value
        return self

    def router_policy(self, value: RouterPolicy) -> "AgentProfileBuilder":
        self._router_policy = value
        return self

    def trace_store(self, value: TraceStore) -> "AgentProfileBuilder":
        self._trace_store = value
        return self

    def build_profile(self) -> AgentProfile:
        return AgentProfile(
            name=self._name,
            prompt=self._prompt,
            description=self._description,
            tools=list(self._tools),
            mcps=list(self._mcps),
            metadata=dict(self._metadata),
            max_iterations=self._max_iterations,
            retry_policy=self._retry_policy,
            router_policy=self._router_policy,
            trace_store=self._trace_store,
        )

    def build(self, *, llm: Any) -> "Agent":
        from shipit_agent.agent import Agent

        profile = self.build_profile()
        return Agent(
            llm=llm,
            prompt=profile.prompt,
            tools=profile.tools,
            mcps=profile.mcps,
            name=profile.name,
            description=profile.description,
            metadata=profile.metadata,
            max_iterations=profile.max_iterations,
            retry_policy=profile.retry_policy,
            router_policy=profile.router_policy,
            trace_store=profile.trace_store,
        )
