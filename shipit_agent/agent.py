"""SHIPIT Agent — the primary agent class with skills, tools, and RAG support.

This module defines :class:`Agent`, the main entry point for building
LLM-powered agents. An Agent combines:

- **LLM** — any model adapter (OpenAI, Anthropic, Bedrock, Groq, etc.)
- **Tools** — built-in or custom tools the LLM can call during execution
- **Skills** — reusable behaviour/workflow templates that shape *how* the
  agent thinks and *which* tools it uses (see ``shipit_agent.skills``)
- **RAG** — optional retrieval-augmented generation for grounded answers
- **Memory / Sessions** — persistent stores for cross-run context
- **Policies** — retry, routing, and replanning configuration

Skill Pipeline (executed on every ``run()`` / ``stream()`` call)::

    ┌─────────────────────────────────────────────────────┐
    │ 1. Collect skills                                    │
    │    ├─ explicit  ``skills=[...]``                      │
    │    ├─ defaults  ``default_skill_ids=[...]``           │
    │    └─ auto      ``find_relevant_skills(prompt)``      │
    │                                                       │
    │ 2. Inject skill prompts into the system prompt        │
    │    └─ ``apply_skill()`` wraps each in HTML markers    │
    │                                                       │
    │ 3. Inject skill tools into the effective tool set     │
    │    └─ ``tool_names_for_skills()`` + builtin map       │
    │                                                       │
    │ 4. Auto-boost max_iterations (4 → 8) if skills add   │
    │    extra tools and the caller didn't set it           │
    │                                                       │
    │ 5. Run the AgentRuntime loop                          │
    └─────────────────────────────────────────────────────┘

Quick start::

    from shipit_agent import Agent

    agent = Agent.with_builtins(llm=llm, project_root="/tmp")
    result = agent.run("Find all TODO comments and summarise them.")

With skills::

    agent = Agent.with_builtins(
        llm=llm,
        skills=["code-workflow-assistant", "database-architect"],
        auto_use_skills=True,
    )
    result = agent.run("Debug the slow billing query and suggest fixes.")
    print(result.metadata["used_skills"])       # → skills used
    print(result.metadata["used_skill_tools"])   # → tools injected by skills
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.agent_run.blocking import BlockingRunMixin
from shipit_agent.agent_run.options import RunOptionsMixin
from shipit_agent.agent_run.streaming import StreamingRunMixin
from shipit_agent.agent_setup.doctor import AgentDoctor, DoctorReport
from shipit_agent.agent_setup.factories import AgentFactoriesMixin
from shipit_agent.agent_setup.initialisation import AgentInitMixin
from shipit_agent.agent_setup.lifecycle import AgentLifecycleMixin
from shipit_agent.agent_setup.preparation import AgentPreparationMixin
from shipit_agent.agent_setup.settings import (
    DEFAULT_SKILLS_PATH,
    AgentSettings,
    SkillLike,
)
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.core.agent_mixin import UpgradeMixin
from shipit_agent.core.models import AgentResult
from shipit_agent.core.reasoning import ReasoningResult, ReasoningRuntime

__all__ = ["Agent", "DEFAULT_SKILLS_PATH", "SkillLike"]


@dataclass(slots=True)
class Agent(
    AgentSettings,
    AgentInitMixin,
    AgentLifecycleMixin,
    AgentFactoriesMixin,
    RunOptionsMixin,
    BlockingRunMixin,
    StreamingRunMixin,
    AgentPreparationMixin,
    UpgradeMixin,
):
    """The primary SHIPIT agent — LLM + tools + skills + RAG in one class.

    **Core fields:**

    - ``llm`` — model adapter (required)
    - ``prompt`` — system prompt; skills append to this at runtime
    - ``tools`` — explicit tool list; skills can inject more automatically
    - ``mcps`` — MCP (Model Context Protocol) server connections
    - ``project_root`` — base directory for file/shell tools

    **Skill fields (see docs/guides/skills.md):**

    - ``skills`` — always attach these (by id string or Skill object)
    - ``default_skill_ids`` — attach from the catalog by id
    - ``auto_use_skills`` — also auto-match skills from the user prompt
    - ``skill_match_limit`` — cap on auto-matched skills per run
    - ``skill_source`` — path to a custom skills.json catalog
    - ``skill_registry`` — supply a pre-built registry instead

    **Power features:**

    - ``rag`` — attach a RAG instance for retrieval-augmented answers
    - ``memory_store`` / ``session_store`` — cross-run persistence
    - ``hooks`` — before/after callbacks for LLM calls and tool runs
    - ``max_iterations`` — loop budget (auto-boosted when skills are active)
    - ``parallel_tool_execution`` — run independent tools concurrently
    - ``context_window_tokens`` — trigger context compaction at this threshold
    """

    #: Cached file-discovered rules (.shipit/rules/*.md) — the only part that
    #: does I/O, so it's read once; `self.rules` stays live and re-read per call.
    _project_rules: Any = field(default=None, repr=False, compare=False)

    # ── internal: handle to the in-flight runtime (for cancel()) ──────
    _active_runtime: Any = field(default=None, repr=False, compare=False)
    _session_runtime_state: dict[str, Any] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _run_lock: Any = field(default=None, init=False, repr=False, compare=False)
    _async_run_lock: Any = field(default=None, init=False, repr=False, compare=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)
    # The sub_agent built for `delegation=`, kept so its thread pool is
    # created once per agent rather than once per run.
    _auto_sub_agent: Any = field(default=None, repr=False, compare=False)

    def plan(self, user_prompt: str, **kwargs: Any) -> AgentResult:
        """Run in read-only **plan mode** — propose a plan without acting.

        Mutating/unknown tools are denied so the agent researches with
        read-only tools and writes a step-by-step plan instead of taking
        action. Returns an :class:`AgentResult` whose ``output`` is the plan.
        """
        import dataclasses

        from shipit_agent.safety.permissions import PermissionEngine

        planner = dataclasses.replace(
            self,
            permission_mode="plan",
            permissions=PermissionEngine(
                mode="plan", callback=self.permission_callback
            ),
        )
        return planner.run(user_prompt, **kwargs)

    def doctor(self, *, env: dict[str, str] | None = None) -> DoctorReport:
        """Run diagnostics and return a health report for this agent."""
        return AgentDoctor(env=env).inspect(self)

    def chat_session(
        self, *, session_id: str, trace_id: str | None = None
    ) -> AgentChatSession:
        """Return a live multi-turn chat session backed by this agent."""
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
        """Run structured reasoning (decomposition + evidence + decision matrix)."""
        return ReasoningRuntime(self).run(
            prompt,
            observations=observations,
            options=options,
            criteria=criteria,
            constraints=constraints,
        )
