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

from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.builtins import get_builtin_tool_map, get_builtin_tools
from shipit_agent.chat_session import AgentChatSession
from shipit_agent.doctor import AgentDoctor, DoctorReport
from shipit_agent.integrations import CredentialStore
from shipit_agent.models import AgentResult, Message
from shipit_agent.policies import RetryPolicy, RouterPolicy
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.reasoning import ReasoningResult, ReasoningRuntime
from shipit_agent.runtime import AgentRuntime
from shipit_agent.skills import (
    FileSkillRegistry,
    Skill,
    SkillRegistry,
    apply_skill,
    find_relevant_skills,
)
from shipit_agent.skills.tool_bundles import tool_names_for_skills
from shipit_agent.stores import MemoryStore, SessionStore
from shipit_agent.tracing import TraceStore

# Path to the packaged skills catalog (ships with the library).
DEFAULT_SKILLS_PATH = Path(__file__).resolve().parent / "skills" / "skills.json"

# A skill reference can be either a resolved ``Skill`` object or a string id
# that will be looked up in the registry at init time.
SkillLike = str | Skill


@dataclass(slots=True)
class Agent:
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

    # ── core ──────────────────────────────────────────────────────────
    llm: Any
    prompt: str = DEFAULT_AGENT_PROMPT
    tools: list[Any] = field(default_factory=list)
    mcps: list[Any] = field(default_factory=list)
    name: str = "shipit"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[Message] = field(default_factory=list)

    # ── persistence ───────────────────────────────────────────────────
    memory_store: MemoryStore | None = None
    session_store: SessionStore | None = None
    credential_store: CredentialStore | None = None
    trace_store: TraceStore | None = None
    session_id: str | None = None
    trace_id: str | None = None

    # ── runtime tuning ────────────────────────────────────────────────
    max_iterations: int = 4                  # auto-boosted → 8 when skills are active
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)
    parallel_tool_execution: bool = False
    hooks: Any = None
    context_window_tokens: int = 0           # 0 = no compaction
    replan_interval: int = 0                 # 0 = no periodic replanning

    # ── RAG ───────────────────────────────────────────────────────────
    rag: Any = None

    # ── project / file tools ──────────────────────────────────────────
    project_root: str | Path = "/tmp"

    # ── skills (see docs/guides/skills.md) ────────────────────────────
    skill_registry: SkillRegistry | None = None        # pre-built registry
    skill_source: str | Path | None = DEFAULT_SKILLS_PATH  # catalog file
    auto_use_skills: bool = True                       # prompt-based matching
    skills: list[SkillLike] = field(default_factory=list)  # always-on skills
    default_skill_ids: list[str] = field(default_factory=list)
    skill_match_limit: int = 3                         # max auto-matched

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        """Wire up RAG tools/prompts and resolve skill references.

        Called automatically after dataclass init. Three things happen:
        1. If ``rag`` is set, inject its tools and prompt section.
        2. If no ``skill_registry`` is provided, build one from ``skill_source``.
        3. Resolve string skill ids in ``self.skills`` into ``Skill`` objects.
        """
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

        # Build the skill registry from the catalog file if not supplied.
        if self.skill_registry is None and self.skill_source:
            skill_path = Path(self.skill_source)
            if skill_path.exists():
                self.skill_registry = FileSkillRegistry(skill_path)

        # Resolve string skill ids → Skill objects (deduplicates by id).
        self.skills = self._resolve_skill_refs(self.skills)

    # ──────────────────────────────────────────────────────────────────
    # Factory
    # ──────────────────────────────────────────────────────────────────

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

        Creates all 30+ built-in tools (file ops, web search, bash, code
        execution, connectors, reasoning helpers, etc.) and merges them
        with any custom ``tools`` the caller provides.

        Tool name collisions are resolved last-write-wins — so a custom
        tool named ``"bash"`` would replace the built-in ``BashTool``.

        Example::

            agent = Agent.with_builtins(
                llm=llm,
                project_root="/my/project",
                skills=["code-workflow-assistant"],
            )
        """
        builtin_tools = get_builtin_tools(
            llm=llm,
            project_root=str(kwargs.get("project_root", "/tmp")),
            workspace_root=workspace_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
        )
        # Merge builtins first, then user tools (user wins on name collision).
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

    # ──────────────────────────────────────────────────────────────────
    # Skill resolution
    # ──────────────────────────────────────────────────────────────────

    def _resolve_skill_ref(self, skill_ref: SkillLike) -> Skill:
        """Convert a string skill id into a ``Skill`` object via the registry."""
        if isinstance(skill_ref, Skill):
            return skill_ref
        if self.skill_registry is None:
            raise ValueError(
                f"Cannot resolve skill '{skill_ref}' because no skill registry is configured."
            )
        skill = self.skill_registry.get(skill_ref)
        if skill is None:
            raise ValueError(f"Unknown skill id: {skill_ref}")
        return skill

    def _resolve_skill_refs(self, skill_refs: list[SkillLike]) -> list[Skill]:
        """Resolve a list of skill refs, deduplicating by id."""
        resolved: list[Skill] = []
        seen_ids: set[str] = set()
        for skill_ref in skill_refs:
            skill = self._resolve_skill_ref(skill_ref)
            if skill.id in seen_ids:
                continue
            resolved.append(skill)
            seen_ids.add(skill.id)
        return resolved

    # ──────────────────────────────────────────────────────────────────
    # Skill public API
    # ──────────────────────────────────────────────────────────────────

    def available_skills(self) -> list[Skill]:
        """Return all skills in the active catalog."""
        if self.skill_registry is None:
            return []
        return self.skill_registry.list()

    def search_skills(self, query: str) -> list[Skill]:
        """Fuzzy-search the active catalog for skills matching *query*."""
        if self.skill_registry is None:
            return []
        return self.skill_registry.search(query)

    def add_skill(self, skill: SkillLike) -> Skill:
        """Attach a skill at runtime (idempotent — skips duplicates)."""
        resolved = self._resolve_skill_ref(skill)
        if resolved.id not in {existing.id for existing in self.skills}:
            self.skills.append(resolved)
        return resolved

    # ──────────────────────────────────────────────────────────────────
    # Skill selection & effective state
    #
    # These methods compute what actually reaches the runtime on each
    # run/stream call. They merge explicit skills, default ids, and
    # auto-matched skills into a single deduplicated list, then derive
    # the effective prompt, tools, and iteration budget.
    # ──────────────────────────────────────────────────────────────────

    def _selected_skills(self, user_prompt: str) -> list[Skill]:
        """Build the final list of skills for this run.

        Priority order (all deduplicated by id):
        1. ``self.skills`` — explicitly attached, always included
        2. ``self.default_skill_ids`` — resolved from the catalog
        3. Auto-matched skills from the prompt (if ``auto_use_skills=True``)
        """
        selected: list[Skill] = []
        seen_ids: set[str] = set()

        # 1. Explicit skills (always active).
        for skill in self.skills:
            if skill.id not in seen_ids:
                selected.append(skill)
                seen_ids.add(skill.id)

        # 2. Default skill ids from the catalog.
        for skill_id in self.default_skill_ids:
            skill = self._resolve_skill_ref(skill_id)
            if skill.id not in seen_ids:
                selected.append(skill)
                seen_ids.add(skill.id)

        # 3. Auto-match from the user prompt (fuzzy search + trigger phrases).
        if self.auto_use_skills and self.skill_registry is not None:
            for skill in find_relevant_skills(
                self.skill_registry,
                user_prompt,
                max_skills=self.skill_match_limit,
            ):
                if skill.id in seen_ids:
                    continue
                selected.append(skill)
                seen_ids.add(skill.id)
        return selected

    def _effective_prompt(self, user_prompt: str) -> str:
        """Return the system prompt with all selected skill blocks appended.

        Each skill's prompt text is wrapped in HTML comment markers::

            <!-- skill:skill-id -->
            ...skill guidance...
            <!-- /skill:skill-id -->
        """
        effective = self.prompt
        for skill in self._selected_skills(user_prompt):
            holder = type("PromptHolder", (), {"prompt": effective})()
            apply_skill(holder, skill)
            effective = holder.prompt
        return effective

    def _effective_tools(
        self, user_prompt: str, *, selected_skills: list[Skill] | None = None
    ) -> list[Any]:
        """Return the merged tool set: explicit tools + skill-injected builtins.

        When *selected_skills* is passed, avoids recomputing ``_selected_skills``.
        Skill-linked tools come from ``SKILL_TOOL_BUNDLES`` — each skill declares
        which built-in tools it needs, and those are resolved from
        ``get_builtin_tool_map()`` and merged into the effective set.

        Tool name collisions are resolved last-write-wins (skill tools can
        override explicit tools with the same name).
        """
        if selected_skills is None:
            selected_skills = self._selected_skills(user_prompt)

        # Start with explicitly configured tools.
        effective: dict[str, Any] = {
            getattr(tool, "name", f"tool_{index}"): tool
            for index, tool in enumerate(self.tools)
        }
        if not selected_skills:
            return list(effective.values())

        # Resolve skill-linked tools from the builtin map and merge in.
        builtin_tool_map = get_builtin_tool_map(
            llm=self.llm,
            project_root=str(self.project_root),
        )
        for tool_name in tool_names_for_skills(selected_skills):
            tool = builtin_tool_map.get(tool_name)
            if tool is not None:
                effective[tool_name] = tool
        return list(effective.values())

    def _skill_tool_names(self, selected_skills: list[Skill]) -> list[str]:
        """Return tool names that were *added* by skills (not already on the agent).

        Used for metadata tracking — tells the caller which extra tools
        were injected because of the selected skills.
        """
        available_names = {getattr(tool, "name", None) for tool in self.tools}
        names: list[str] = []
        seen: set[str] = set()
        for tool_name in tool_names_for_skills(selected_skills):
            if tool_name in available_names or tool_name in seen:
                continue
            names.append(tool_name)
            seen.add(tool_name)
        return names

    def _effective_max_iterations(self, selected_skills: list[Skill]) -> int:
        """Auto-boost iteration budget when skills inject extra tools.

        Skills bring additional tools that the agent needs more turns to
        use effectively. When the caller left ``max_iterations`` at the
        default (4), we raise it to 8 so the agent can complete multi-step
        skill-driven workflows without cutting off early.

        An explicit override (max_iterations > 4) is always respected.
        """
        if selected_skills and self.max_iterations <= 4:
            return max(8, self.max_iterations)
        return self.max_iterations

    # ──────────────────────────────────────────────────────────────────
    # Run (synchronous)
    # ──────────────────────────────────────────────────────────────────

    def run(self, user_prompt: str, *, output_schema: Any = None) -> AgentResult:
        """Execute the agent loop and return the final result.

        Steps:
        1. Optionally append structured output schema instructions.
        2. Compute selected skills once — reused for prompt, tools, metadata.
        3. Build the ``AgentRuntime`` with effective prompt, tools, and
           boosted iteration budget.
        4. Run the loop: LLM call → tool execution → repeat.
        5. Optionally parse the output against ``output_schema``.
        6. Return ``AgentResult`` with output, messages, events, and metadata.
        """
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

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(user_prompt, selected_skills=selected_skills)
        skill_tool_names = self._skill_tool_names(selected_skills)

        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
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
            max_iterations=self._effective_max_iterations(selected_skills),
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
            parallel_tool_execution=self.parallel_tool_execution,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            replan_interval=self.replan_interval,
        )
        state, response = runtime.run(effective_user_prompt)

        # Optionally parse structured output from the LLM response.
        parsed = None
        if output_schema and response.content:
            try:
                from shipit_agent.structured import parse_structured_output

                parsed = parse_structured_output(response.content, output_schema)
            except Exception:
                parsed = None

        rag_sources = self.rag.end_run() if self.rag is not None else []

        # Attach skill metadata so callers can see what was used.
        result_metadata = dict(response.metadata)
        result_metadata["used_skills"] = [skill.id for skill in selected_skills]
        result_metadata["used_skill_tools"] = skill_tool_names

        return AgentResult(
            output=response.content,
            messages=state.messages,
            events=state.events,
            tool_results=state.tool_results,
            metadata=result_metadata,
            parsed=parsed,
            rag_sources=rag_sources,
        )

    # ──────────────────────────────────────────────────────────────────
    # Stream (yields events as they happen)
    # ──────────────────────────────────────────────────────────────────

    def stream(self, user_prompt: str):
        """Stream agent events (tool calls, completions, etc.) as they happen.

        Same skill pipeline as ``run()`` but yields ``AgentEvent`` objects
        instead of blocking until completion. Useful for UIs that want
        real-time progress feedback.
        """
        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(user_prompt, selected_skills=selected_skills)

        runtime = AgentRuntime(
            llm=self.llm,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                "used_skills": [skill.id for skill in selected_skills],
                "used_skill_tools": self._skill_tool_names(selected_skills),
                **self.metadata,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self.trace_store,
            trace_id=self.trace_id,
            max_iterations=self._effective_max_iterations(selected_skills),
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

    # ──────────────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────────────

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
