"""DeepAgent — power-user ``create_deep_agent`` factory.

Side-by-side with LangChain's ``deepagents``:

==========================  ============================  ==========================
Capability                  LangChain ``deepagents``       shipit ``DeepAgent``
==========================  ============================  ==========================
Planning tool                ``write_todos``                ``plan_task`` ✅
Virtual filesystem           ``ls``/``read``/``write``      ``workspace_files`` ✅
Sub-agent spawning           ``task``                       ``sub_agent`` ✅
Opinionated prompt           ✅                              ✅
Multi-turn chat              LangGraph state                ``DeepAgent.chat()`` ✅
Memory across turns          MemoryStore                    ``AgentMemory`` ✅
RAG with auto citations      (BYO)                          ``rag=`` ✨
Verification loop            (BYO)                          ``verify=True`` ✨
Reflection / self-critique   (BYO)                          ``reflect=True`` ✨
Goal-driven mode             (BYO)                          ``goal=Goal(...)`` ✨
Thought decomposition tool   (BYO)                          ``decompose_thought`` ✨
Evidence synthesis tool      (BYO)                          ``synthesize_evidence`` ✨
Decision matrix tool         (BYO)                          ``decision_matrix`` ✨
Verifier tool                (BYO)                          ``verify_output`` ✨
Auto context compaction      LangGraph                      ``context_window_tokens`` ✅
Parallel tool execution      (BYO)                          ``parallel_tool_execution`` ✅
Retry policy                 (BYO)                          ``retry_policy`` ✅
Hooks (before/after LLM)     callbacks                      ``hooks=`` ✅
Streaming events             ✅                              ✅ (15 event types)
Tracing                      LangSmith                      ``trace_store`` ✅
==========================  ============================  ==========================

Quick start::

    from shipit_agent.deep import DeepAgent
    agent = DeepAgent.with_builtins(llm=llm)
    result = agent.run("Investigate the auth bug and propose a fix.")

Power user::

    agent = DeepAgent.with_builtins(
        llm=llm,
        rag=my_rag,
        verify=True,
        reflect=True,
        memory=AgentMemory.default(llm=llm, embedding_fn=embed),
        max_iterations=20,
        context_window_tokens=200_000,
    )

Live chat::

    chat = agent.chat(session_id="user-42")
    for event in chat.stream("Hi"):
        print(event.message)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shipit_agent.agent import DEFAULT_SKILLS_PATH
from shipit_agent.builtins import get_builtin_tools
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.models import AgentEvent, AgentResult
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.skills import Skill, SkillRegistry
from shipit_agent.stores import InMemorySessionStore, SessionStore

from ..goal_agent import Goal, GoalAgent, GoalResult
from ..reflective_agent import ReflectionResult, ReflectiveAgent
from .delegation import AgentDelegationTool, build_delegation_tool
from .prompt import DEEP_AGENT_PROMPT
from .toolset import deep_tool_set, merge_tools
from .verification import verify_text


@dataclass(slots=True)
class DeepAgent:
    """Power-user ``create_deep_agent``-style factory.

    Wraps :class:`shipit_agent.Agent` and bundles the full deep-agent
    toolset, opinionated prompting, and optional **verification**,
    **reflection**, **goal-driven**, and **memory** layers — all behind
    a single constructor.
    """

    # ---- core --------------------------------------------------------------
    llm: Any
    name: str = "shipit-deep-agent"
    description: str = "A deep agent that plans, verifies, and uses a workspace."
    prompt: str = DEEP_AGENT_PROMPT
    extra_tools: list[Any] = field(default_factory=list)
    mcps: list[Any] = field(default_factory=list)
    workspace_root: str = ".shipit_workspace"
    project_root: str | Path = "/tmp"
    # Sub-agents the deep agent can delegate to via the
    # ``delegate_to_agent`` tool. Pass a list (names derived from each
    # agent's ``.name`` attribute) or a dict[name, agent].
    agents: Any = None

    # ---- power features ---------------------------------------------------
    rag: Any = None
    memory: Any = None
    memory_store: Any = None
    session_store: SessionStore | None = None
    verify: bool = False
    reflect: bool = False
    reflect_threshold: float = 0.8
    reflect_max_iterations: int = 3
    goal: Goal | None = None

    # ---- runtime tuning ---------------------------------------------------
    max_iterations: int = 8
    parallel_tool_execution: bool = True
    context_window_tokens: int = 0
    retry_policy: RetryPolicy | None = None
    router_policy: RouterPolicy | None = None
    hooks: Any = None
    trace_store: Any = None
    credential_store: Any = None
    # ---- skills (forwarded to inner Agent — see docs/guides/skills.md) ----
    # All skill fields are passed through to the inner Agent unchanged.
    # DeepAgent.add_skill() and .search_skills() delegate to the inner Agent.
    # Skills inject both prompt guidance and tools into the inner Agent's
    # runtime, so the DeepAgent's LLM sees the skill instructions and can
    # call the skill-linked tools during execution.
    skill_registry: SkillRegistry | None = None
    skill_source: str | Path | None = DEFAULT_SKILLS_PATH
    auto_use_skills: bool = True
    skills: list[str | Skill] = field(default_factory=list)
    default_skill_ids: list[str] = field(default_factory=list)
    skill_match_limit: int = 3

    # ---- builtins ---------------------------------------------------------
    use_builtins: bool = False
    web_search_provider: str = "duckduckgo"
    web_search_api_key: str | None = None

    agent_kwargs: dict[str, Any] = field(default_factory=dict)
    _agent: Any = None

    # ====================================================================
    # Factories
    # ====================================================================

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        prompt: str = DEEP_AGENT_PROMPT,
        name: str = "shipit-deep-agent",
        description: str = "A deep agent that plans, verifies, and uses a workspace.",
        extra_tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        workspace_root: str = ".shipit_workspace",
        project_root: str | Path = "/tmp",
        web_search_provider: str = "duckduckgo",
        web_search_api_key: str | None = None,
        rag: Any = None,
        memory: Any = None,
        memory_store: Any = None,
        session_store: SessionStore | None = None,
        verify: bool = False,
        reflect: bool = False,
        reflect_threshold: float = 0.8,
        reflect_max_iterations: int = 3,
        goal: Goal | None = None,
        agents: Any = None,
        max_iterations: int = 8,
        parallel_tool_execution: bool = True,
        context_window_tokens: int = 0,
        retry_policy: RetryPolicy | None = None,
        router_policy: RouterPolicy | None = None,
        hooks: Any = None,
        trace_store: Any = None,
        credential_store: Any = None,
        skill_registry: SkillRegistry | None = None,
        skill_source: str | Path | None = DEFAULT_SKILLS_PATH,
        auto_use_skills: bool = True,
        skills: list[str | Skill] | None = None,
        default_skill_ids: list[str] | None = None,
        skill_match_limit: int = 3,
        **agent_kwargs: Any,
    ) -> "DeepAgent":
        """Build a DeepAgent that also bundles the full built-in tool catalogue."""
        return cls(
            llm=llm,
            name=name,
            description=description,
            prompt=prompt,
            extra_tools=list(extra_tools or []),
            mcps=list(mcps or []),
            workspace_root=workspace_root,
            project_root=project_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            rag=rag,
            memory=memory,
            memory_store=memory_store,
            session_store=session_store,
            verify=verify,
            reflect=reflect,
            reflect_threshold=reflect_threshold,
            reflect_max_iterations=reflect_max_iterations,
            goal=goal,
            agents=agents,
            max_iterations=max_iterations,
            parallel_tool_execution=parallel_tool_execution,
            context_window_tokens=context_window_tokens,
            retry_policy=retry_policy,
            router_policy=router_policy,
            hooks=hooks,
            trace_store=trace_store,
            credential_store=credential_store,
            skill_registry=skill_registry,
            skill_source=skill_source,
            auto_use_skills=auto_use_skills,
            skills=list(skills or []),
            default_skill_ids=list(default_skill_ids or []),
            skill_match_limit=skill_match_limit,
            use_builtins=True,
            agent_kwargs=agent_kwargs,
        )

    # ====================================================================
    # Lifecycle
    # ====================================================================

    def __post_init__(self) -> None:
        self._agent = self._build_agent()
        self.skills = list(self._agent.skills)

    def _builtin_tools(self) -> list[Any]:
        if not self.use_builtins:
            return []
        return get_builtin_tools(
            llm=self.llm,
            project_root=str(self.project_root),
            workspace_root=self.workspace_root,
            web_search_provider=self.web_search_provider,
            web_search_api_key=self.web_search_api_key,
        )

    def _resolve_memory(self) -> tuple[Any, list[Any]]:
        """Return ``(memory_store, history_messages)`` derived from ``self.memory``.

        ``AgentMemory.knowledge`` is a :class:`SemanticMemory`, not a
        :class:`MemoryStore` — they have different interfaces. So when
        ``self.memory`` is an :class:`AgentMemory` we **only** hydrate
        ``history`` from ``memory.get_conversation_messages()`` and leave
        ``memory_store`` alone. Pass ``memory_store=`` explicitly if you
        want the runtime's memory tool wired up too.
        """
        memory_store = self.memory_store
        history: list[Any] = []
        if self.memory is None:
            return memory_store, history
        if hasattr(self.memory, "get_conversation_messages"):
            history = list(self.memory.get_conversation_messages())
        return memory_store, history

    def _agent_kwargs(self, tools: list[Any]) -> dict[str, Any]:
        memory_store, history = self._resolve_memory()
        kwargs: dict[str, Any] = {
            "llm": self.llm,
            "prompt": self.prompt,
            "tools": tools,
            "mcps": list(self.mcps),
            "name": self.name,
            "description": self.description,
            "rag": self.rag,
            "memory_store": memory_store,
            "session_store": self.session_store,
            "max_iterations": self.max_iterations,
            "parallel_tool_execution": self.parallel_tool_execution,
            "context_window_tokens": self.context_window_tokens,
            "skill_registry": self.skill_registry,
            "skill_source": self.skill_source,
            "auto_use_skills": self.auto_use_skills,
            "skills": list(self.skills),
            "default_skill_ids": list(self.default_skill_ids),
            "skill_match_limit": self.skill_match_limit,
            "project_root": self.project_root,
        }
        if history:
            kwargs["history"] = history
        for name, value in (
            ("retry_policy", self.retry_policy),
            ("router_policy", self.router_policy),
            ("hooks", self.hooks),
            ("trace_store", self.trace_store),
            ("credential_store", self.credential_store),
        ):
            if value is not None:
                kwargs[name] = value
        kwargs.update(self.agent_kwargs)
        return kwargs

    def _delegation_tool_list(self) -> list[Any]:
        tool = build_delegation_tool(self.agents)
        return [tool] if tool is not None else []

    def _build_agent(self) -> Any:
        from shipit_agent.agent import Agent

        tools = merge_tools(
            self.extra_tools,
            self._builtin_tools(),
            deep_tool_set(llm=self.llm, workspace_root=self.workspace_root),
            self._delegation_tool_list(),
        )
        return Agent(**self._agent_kwargs(tools))

    # ====================================================================
    # Inner-agent passthroughs
    # ====================================================================

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

    # ====================================================================
    # Run / stream
    # ====================================================================

    def run(self, user_prompt: str | None = None, **kwargs: Any) -> Any:
        """Run the deep agent.

        - When ``goal`` is set → delegates to :class:`GoalAgent`.
        - Else when ``reflect=True`` → delegates to :class:`ReflectiveAgent`.
        - Otherwise runs the inner :class:`Agent`.

        With ``verify=True``, after the main run the agent invokes its
        ``verify_output`` tool against the final answer and the success
        criteria (taken from the goal, when present).
        """
        if self.goal is not None:
            return self._run_goal()
        if self.reflect:
            return self._run_reflective(user_prompt or "")

        result = self._agent.run(user_prompt or "", **kwargs)
        if self.verify:
            self._post_verify(result)
        return result

    def stream(self, user_prompt: str | None = None):
        """Stream events from the active execution mode."""
        if self.goal is not None:
            yield from self._stream_goal()
            return
        if self.reflect:
            yield from self._stream_reflective(user_prompt or "")
            return

        last_event: AgentEvent | None = None
        for event in self._agent.stream(user_prompt or ""):
            yield event
            if event.type == "run_completed":
                last_event = event

        if self.verify and last_event is not None:
            verdict = verify_text(last_event.payload.get("output", ""), goal=self.goal)
            yield AgentEvent(
                type="run_completed",
                message="verification_completed",
                payload={"verification": verdict},
            )

    # ---- goal-driven mode ----------------------------------------------

    def _build_goal_agent(self) -> GoalAgent:
        return GoalAgent(
            llm=self.llm,
            tools=list(self._agent.tools),
            mcps=list(self.mcps),
            goal=self.goal,
            prompt=self.prompt,
            rag=self.rag,
        )

    def _run_goal(self) -> GoalResult:
        return self._build_goal_agent().run()

    def _stream_goal(self):
        yield from self._build_goal_agent().stream()

    # ---- reflective mode -----------------------------------------------

    def _build_reflective_agent(self) -> ReflectiveAgent:
        return ReflectiveAgent(
            llm=self.llm,
            tools=list(self._agent.tools),
            mcps=list(self.mcps),
            quality_threshold=self.reflect_threshold,
            max_reflections=self.reflect_max_iterations,
            prompt=self.prompt,
            rag=self.rag,
        )

    def _run_reflective(self, user_prompt: str) -> ReflectionResult:
        return self._build_reflective_agent().run(user_prompt)

    def _stream_reflective(self, user_prompt: str):
        agent = self._build_reflective_agent()
        if hasattr(agent, "stream"):
            yield from agent.stream(user_prompt)
            return
        result = agent.run(user_prompt)
        yield AgentEvent(
            type="run_completed",
            message="reflective run completed",
            payload={"output": getattr(result, "output", str(result))},
        )

    # ---- verification --------------------------------------------------

    def _post_verify(self, result: AgentResult) -> None:
        result.metadata["verification"] = verify_text(
            result.output or "", goal=self.goal
        )

    # ====================================================================
    # Live chat
    # ====================================================================

    def chat(
        self,
        *,
        session_id: str = "default",
        trace_id: str | None = None,
        session_store: SessionStore | None = None,
    ) -> AgentChatSession:
        """Return an :class:`AgentChatSession` for live multi-turn chat."""
        store = session_store or self.session_store or InMemorySessionStore()
        return AgentChatSession(
            agent=self._agent,
            session_id=session_id,
            trace_id=trace_id,
            session_store=store,
        )


# ----------------------------------------------------------------------------
# Functional convenience helper
# ----------------------------------------------------------------------------


def create_deep_agent(
    *,
    llm: Any,
    tools: list[Any] | None = None,
    agents: Any = None,
    system_prompt: str = DEEP_AGENT_PROMPT,
    rag: Any = None,
    use_builtins: bool = False,
    verify: bool = False,
    reflect: bool = False,
    goal: Goal | None = None,
    memory: Any = None,
    max_iterations: int = 8,
    **kwargs: Any,
) -> DeepAgent:
    """LangChain-style ``create_deep_agent`` factory function — but more powerful.

    Drop-in alternative to :class:`DeepAgent` with the keyword names
    LangChain users expect plus the power-user flags this library
    exposes.

    Example::

        from shipit_agent.deep import create_deep_agent

        def get_weather(city: str) -> str:
            \"\"\"Get weather for a given city.\"\"\"
            return f"It's always sunny in {city}!"

        agent = create_deep_agent(
            tools=[get_weather],
            llm=llm,
            system_prompt="You are a helpful weather assistant.",
            verify=True,
            reflect=True,
            rag=my_rag,
        )

        result = agent.run("what is the weather in sf")

    Sub-agents — wire your own agents as delegates::

        researcher = Agent.with_builtins(llm=llm, prompt="You research.")
        writer     = Agent.with_builtins(llm=llm, prompt="You write.")
        critic     = ReflectiveAgent.with_builtins(llm=llm)

        agent = create_deep_agent(
            llm=llm,
            agents=[researcher, writer, critic],   # ← named sub-agents
            use_builtins=True,
        )

        # The deep agent now has a `delegate_to_agent` tool it can call
        # to hand off well-scoped sub-tasks to any of the named agents.
        # This makes it behave like a Supervisor — but more powerful,
        # since it still has the full deep-agent toolset itself.
        result = agent.run("Investigate the auth bug, draft a fix, then review.")
    """
    extra_tools: list[Any] = []
    for tool in tools or []:
        if callable(tool) and not hasattr(tool, "schema"):
            from shipit_agent.tools import FunctionTool

            extra_tools.append(FunctionTool.from_callable(tool))
        else:
            extra_tools.append(tool)

    factory = DeepAgent.with_builtins if use_builtins else DeepAgent
    return factory(
        llm=llm,
        prompt=system_prompt,
        extra_tools=extra_tools,
        agents=agents,
        rag=rag,
        verify=verify,
        reflect=reflect,
        goal=goal,
        memory=memory,
        max_iterations=max_iterations,
        **kwargs,
    )


__all__ = ["DeepAgent", "create_deep_agent"]
