from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.builtins import get_builtin_tools
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.doctor import AgentDoctor, DoctorReport
from shipit_agent.integrations import CredentialStore
from shipit_agent.models import AgentResult, Message
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.reasoning import ReasoningResult, ReasoningRuntime
from shipit_agent.runtime import AgentRuntime
from shipit_agent.stores import MemoryStore, SessionStore
from shipit_agent.tracing import TraceStore


@dataclass(slots=True)
class Agent:
    llm: Any
    prompt: str = DEFAULT_AGENT_PROMPT
    tools: list[Any] = field(default_factory=list)
    mcps: list[Any] = field(default_factory=list)
    name: str = "shipit"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[Message] = field(default_factory=list)
    memory_store: MemoryStore | None = None
    session_store: SessionStore | None = None
    credential_store: CredentialStore | None = None
    trace_store: TraceStore | None = None
    session_id: str | None = None
    trace_id: str | None = None
    max_iterations: int = 4
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        prompt: str = DEFAULT_AGENT_PROMPT,
        name: str = "shipit",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        workspace_root: str = ".shipit_workspace",
        web_search_provider: str = "duckduckgo",
        web_search_api_key: str | None = None,
        web_search_config: dict[str, Any] | None = None,
        mcps: list[Any] | None = None,
        **kwargs: Any,
    ) -> "Agent":
        tools = get_builtin_tools(
            llm=llm,
            workspace_root=workspace_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
        )
        return cls(
            llm=llm,
            prompt=prompt,
            tools=tools,
            mcps=list(mcps or []),
            name=name,
            description=description,
            metadata=metadata or {},
            **kwargs,
        )

    def run(self, user_prompt: str) -> AgentResult:
        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self.prompt,
            tools=self.tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self.trace_store,
            trace_id=self.trace_id,
            max_iterations=self.max_iterations,
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
        )
        state, response = runtime.run(user_prompt)
        return AgentResult(
            output=response.content,
            messages=state.messages,
            events=state.events,
            tool_results=state.tool_results,
            metadata=dict(response.metadata),
        )

    def stream(self, user_prompt: str):
        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self.prompt,
            tools=self.tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self.trace_store,
            trace_id=self.trace_id,
            max_iterations=self.max_iterations,
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
        )
        for event in runtime.stream(user_prompt):
            yield event

    def doctor(self, *, env: dict[str, str] | None = None) -> DoctorReport:
        return AgentDoctor(env=env).inspect(self)

    def chat_session(self, *, session_id: str, trace_id: str | None = None) -> AgentChatSession:
        return AgentChatSession(agent=self, session_id=session_id, trace_id=trace_id)

    def reason(
        self,
        prompt: str,
        *,
        observations: list[str] | None = None,
        options: list[str] | None = None,
        criteria: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> ReasoningResult:
        return ReasoningRuntime(self).run(
            prompt,
            observations=observations,
            options=options,
            criteria=criteria,
            constraints=constraints,
        )
