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
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.core.models import AgentEvent, Message
from shipit_agent.core.policies import RetryPolicy, RouterPolicy
from shipit_agent.skills import Skill, SkillRegistry
from shipit_agent.stores import InMemorySessionStore, SessionStore

from ..goal_agent import Goal
from .assembly import _DeepAgentAssembly
from .builders import _DeepAgentBuilders
from .modes import _DeepAgentModes
from .prompt import DEEP_AGENT_PROMPT
from .registry import _DeepAgentRegistry
from .verification import verify_text


@dataclass(slots=True)
class DeepAgent(
    _DeepAgentBuilders,
    _DeepAgentAssembly,
    _DeepAgentModes,
    _DeepAgentRegistry,
):
    """Power-user ``create_deep_agent``-style factory.

    Wraps :class:`shipit_agent.Agent` and bundles the full deep-agent
    toolset, opinionated prompting, and optional **verification**,
    **reflection**, **goal-driven**, and **memory** layers — all behind
    a single constructor.
    """

    # ---- core --------------------------------------------------------------
    llm: Any
    decision_llm: Any = None
    progress_summaries: bool = False
    name: str = "shipit-deep-agent"
    description: str = "A deep agent that plans, verifies, and uses a workspace."
    prompt: str = DEEP_AGENT_PROMPT
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[Message] = field(default_factory=list)
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
    session_id: str | None = None
    verify: bool = False
    reflect: bool = False
    reflect_threshold: float = 0.8
    reflect_max_iterations: int = 3
    goal: Goal | None = None
    # Process-supervision verifier (v1.0.8). Wraps every tool with a
    # pre-call veto check and exposes progress-rating on each step.
    # See ``shipit_agent.verifier``.
    verifier: Any = None

    # ---- runtime tuning ---------------------------------------------------
    max_iterations: int = 8
    parallel_tool_execution: bool = True
    max_tool_concurrency: int | None = None
    context_window_tokens: int = 0
    max_tool_output_chars: int = 0
    replan_interval: int = 0
    retry_policy: RetryPolicy | None = None
    router_policy: RouterPolicy | None = None
    hooks: Any = None
    trace_store: Any = None
    trace_id: str | None = None
    credential_store: Any = None
    permission_mode: str = "default"
    permissions: Any = None
    permission_callback: Any = None
    guardrails: Any = None
    approvals: Any = None
    code_mode: bool = False
    lockdown: Any = None
    heal_tool_calls: bool = True
    # ---- skills (forwarded to inner Agent — see docs/guides/skills.md) ----
    # All skill fields are passed through to the inner Agent unchanged.
    # DeepAgent.add_skill() and .search_skills() delegate to the inner Agent.
    # Skills inject both prompt guidance and tools into the inner Agent's
    # runtime, so the DeepAgent's LLM sees the skill instructions and can
    # call the skill-linked tools during execution.
    skill_registry: SkillRegistry | None = None
    skill_source: str | Path | None = DEFAULT_SKILLS_PATH
    auto_use_skills: bool = True
    auto_project_skills: bool = True
    skills: list[str | Skill] = field(default_factory=list)
    default_skill_ids: list[str] = field(default_factory=list)
    skill_match_limit: int = 3

    # ---- builtins ---------------------------------------------------------
    use_builtins: bool = False
    web_search_provider: str = "duckduckgo"
    web_search_api_key: str | None = None
    web_search_config: dict[str, Any] | None = None

    agent_kwargs: dict[str, Any] = field(default_factory=dict)
    _agent: Any = None

    # ====================================================================
    # Factories
    # ====================================================================

    # ====================================================================
    # Lifecycle
    # ====================================================================

    def __post_init__(self) -> None:
        self._agent = self._build_agent()
        self.skills = list(self._agent.skills)

    # ====================================================================
    # Inner-agent passthroughs
    # ====================================================================

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

    # ---- verification --------------------------------------------------

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


__all__ = ["DeepAgent"]


def __getattr__(name: str) -> Any:
    # create_deep_agent moved to .create, which imports DeepAgent from here.
    if name == "create_deep_agent":
        from .create import create_deep_agent

        return create_deep_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
