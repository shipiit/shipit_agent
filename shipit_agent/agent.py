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
    parallel_tool_execution: bool = False
    hooks: Any = None
    context_window_tokens: int = 0
    replan_interval: int = 0
    rag: Any = None

    def __post_init__(self) -> None:
        if self.rag is not None:
            # Auto-wire RAG tools and augment the prompt once per Agent.
            existing_names = {getattr(t, "name", None) for t in self.tools}
            for tool in self.rag.as_tools():
                if tool.name not in existing_names:
                    self.tools.append(tool)
                    existing_names.add(tool.name)
            rag_section = self.rag.prompt_section()
            if rag_section and rag_section not in self.prompt:
                self.prompt = f"{self.prompt}\n\n{rag_section}"

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
        rag: Any = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> "Agent":
        """Build an Agent that ships with the full built-in tool catalogue.

        ``tools=`` may be passed alongside the builtins — user tools are
        merged in and any tool whose ``name`` collides with a builtin
        replaces the builtin (last-write-wins).
        """
        builtin_tools = get_builtin_tools(
            llm=llm,
            workspace_root=workspace_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
        )
        merged: dict[str, Any] = {}
        for tool in (*builtin_tools, *(tools or [])):
            tool_name = getattr(tool, "name", None)
            if tool_name:
                merged[tool_name] = tool
        return cls(
            llm=llm,
            prompt=prompt,
            tools=list(merged.values()),
            mcps=list(mcps or []),
            name=name,
            description=description,
            metadata=metadata or {},
            rag=rag,
            **kwargs,
        )

    def run(self, user_prompt: str, *, output_schema: Any = None) -> AgentResult:
        # Append schema instructions to the USER prompt (not system prompt)
        # so the model can still use tools normally and only formats the
        # final answer as JSON. Bedrock returns empty content when schema
        # instructions pollute the system prompt.
        effective_user_prompt = user_prompt
        if output_schema:
            from shipit_agent.structured import build_schema_prompt

            effective_user_prompt = user_prompt + build_schema_prompt(output_schema)

        if self.rag is not None:
            self.rag.begin_run()

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
            parallel_tool_execution=self.parallel_tool_execution,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            replan_interval=self.replan_interval,
        )
        state, response = runtime.run(effective_user_prompt)

        parsed = None
        if output_schema and response.content:
            try:
                from shipit_agent.structured import parse_structured_output

                parsed = parse_structured_output(response.content, output_schema)
            except Exception:
                parsed = None

        rag_sources = self.rag.end_run() if self.rag is not None else []

        return AgentResult(
            output=response.content,
            messages=state.messages,
            events=state.events,
            tool_results=state.tool_results,
            metadata=dict(response.metadata),
            parsed=parsed,
            rag_sources=rag_sources,
        )

    def stream(self, user_prompt: str):
        if self.rag is not None:
            self.rag.begin_run()

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
            parallel_tool_execution=self.parallel_tool_execution,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            replan_interval=self.replan_interval,
        )
        for event in runtime.stream(user_prompt):
            yield event

        if self.rag is not None:
            from shipit_agent.models import AgentEvent

            sources = self.rag.end_run()
            if sources:
                yield AgentEvent(
                    type="rag_sources",
                    message=f"Captured {len(sources)} RAG source(s)",
                    payload={"sources": [s.to_dict() for s in sources]},
                )

    def doctor(self, *, env: dict[str, str] | None = None) -> DoctorReport:
        return AgentDoctor(env=env).inspect(self)

    def chat_session(
        self, *, session_id: str, trace_id: str | None = None
    ) -> AgentChatSession:
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
