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

import logging
from dataclasses import dataclass, field
from pathlib import Path
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

logger = logging.getLogger(__name__)

# Path to the packaged skills catalog (ships with the library).
DEFAULT_SKILLS_PATH = Path(__file__).resolve().parent / "skills" / "skills.json"

# A skill reference can be either a resolved ``Skill`` object or a string id
# that will be looked up in the registry at init time.
SkillLike = str | Skill

# Views ``run_live`` knows how to draw. Anything else is a typo, and used to
# fall through to the default renderer without a word.
_LIVE_STYLES = frozenset({"auto", "rich", "plain", "tree", "modern"})


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
    # Accepted for compatibility and no longer used for progress narration,
    # which costs no model call at all now. Kept so existing callers keep
    # working rather than raising on an unexpected keyword.
    decision_llm: Any = None
    # Emit public ``agent_decision`` / ``agent_observation`` progress events.
    # Decisions use only prose the primary model already produced; observations
    # use factual tool metadata. No summarizer call and no invented reasoning.
    progress_summaries: bool = False
    #: Short standing instruction placed at the very END of the context on
    #: every step. Use it for the one or two requirements that must hold
    #: every time; a model attends far more reliably to the tokens closest
    #: to generation than to the top of a long system prompt.
    reminder: str | None = None
    #: Replace earlier turns' tool payloads with a short notice, keeping
    #: the calls and arguments. A tool result is re-sent on every request
    #: of every later turn; once its content is in the answer below it,
    #: the payload is pure cost. Set False to keep whole transcripts.
    evict_prior_tool_outputs: bool = True
    #: A ``shipit_agent.multimodal.MediaParser`` (or compatible). When set,
    #: inline media references in the user prompt — ``[https://…/x.png]``,
    #: ``![alt](url)``, ``[media:id]`` — are turned into image/document
    #: content blocks on the user turn. Needs a vision-capable model.
    #: Independent of ``run(images=[...])``, which attaches explicitly.
    media_parser: Any = None
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
    #: Report this agent's runs through shipit-watcher — traces, the agent
    #: graph, scores, datasets and the local ledger.
    #:
    #: ``True`` attaches it, ``False`` never does, and the default ``"auto"``
    #: attaches it only when shipit-watcher is installed *and* configured
    #: with credentials. Auto is safe as a default precisely because
    #: watcher answers "am I configured?" itself: an unconfigured install
    #: emits nothing rather than erroring, so this cannot turn a working
    #: agent into a broken one.
    #:
    #: An explicit ``trace_store`` always wins — passing one means you have
    #: already decided where runs go.
    observability: bool | str = "auto"
    session_id: str | None = None
    trace_id: str | None = None

    # ── runtime tuning ────────────────────────────────────────────────
    # A hard task should not stop after a handful of tool calls. 4 was too
    # tight — a real multi-step run (read several files, edit, test, fix)
    # blows through it and gets cut to a summary before the context window
    # is the real constraint. Raised to 12; skills boost further; autopilot
    # sets its own.
    max_iterations: int = 12  # auto-boosted → 16 when skills are active
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)
    parallel_tool_execution: bool = False
    # None means no cap; otherwise bound concurrent local tool calls per turn.
    max_tool_concurrency: int | None = None
    hooks: Any = None
    context_window_tokens: int = 0  # 0 = no compaction
    # Bound only the model-visible copy; AgentResult keeps complete tool
    # output. Capped by default: a message list is cumulative, so one
    # 138,000-character tool result is not paid once — it is re-sent on
    # every turn that follows it. Measured on a real run, five iterations
    # cost 507,000 input tokens because nothing bounded a single MCP reply.
    # Set 0 for no cap if a tool's whole body genuinely has to reach the
    # model.
    max_tool_output_chars: int = 16_000
    # Parallel calls share this model-context budget. Complete outputs remain
    # available in AgentResult and live tool events.
    max_tool_output_group_chars: int = 48_000
    # Optimized agents spill complete large results under .shipit so the model
    # can fetch omitted sections without paying for the whole body every turn.
    persist_large_tool_outputs: bool = False
    replan_interval: int = 0  # 0 = no periodic replanning

    # ── RAG ───────────────────────────────────────────────────────────
    rag: Any = None

    # ── Verifier network (v1.0.8) ─────────────────────────────────────
    # Optional ``VerifierNetwork`` that runs pre-tool veto checks on every
    # tool call and (when used in autopilot-style loops) progress checks
    # between iterations. See ``shipit_agent/verifier/``.
    verifier: Any = None

    # ── permissions / control plane (v1.0.11) ─────────────────────────
    # Rule-based gate over tool calls. Set a mode
    # ("default" | "acceptEdits" | "plan" | "bypass"), or pass a full
    # ``PermissionEngine`` / kwargs dict via ``permissions``, or a
    # ``permission_callback(name, args) -> PermissionResult | None`` for
    # programmatic human-in-the-loop approval. See ``shipit_agent.permissions``.
    permission_mode: str = "default"
    permissions: Any = None
    permission_callback: Any = None

    # ── guardrails (content-level protection) ─────────────────────────
    # A ``Guardrails`` instance: blocks prompt-injection inputs, redacts
    # secrets/PII from outputs, and denies tool calls whose arguments match
    # configured patterns. See ``shipit_agent.guardrails``.
    guardrails: Any = None

    # ── deferred approvals (Cloudflare-OS style) ──────────────────────
    # An ``ApprovalQueue`` (or ``True`` for a fresh one). Side-effecting
    # tools the policy marks ``ask`` are queued instead of blocking the run;
    # you approve later, in bulk. Tools whose result the agent reasons over
    # declare ``await_decision`` and still block. See shipit_agent.approvals.
    approvals: Any = None

    # ── code mode (v1.0.19) ───────────────────────────────────────────
    # Collapse the tool catalogue into a small core set plus an `env` of
    # resource bindings reachable from `execute_code`. Cuts the tool-schema
    # block by ~79% and lets one call compose several resources. Bindings are
    # gated exactly as the equivalent tool calls. See shipit_agent.codemode.
    code_mode: bool = False

    # ── deferred tool loading (v1.7) ──────────────────────────────────
    # Tool paging: core tools keep their full schema in
    # every request; everything else is listed by NAME only until
    # `tool_search` (or a direct call) loads it. Cuts the fixed per-step
    # schema cost to the working set. ``True`` defers everything outside
    # the core set; a list of names defers exactly those. Ignored when
    # ``code_mode`` is on (code mode collapses the catalogue its own way).
    deferred_tools: Any = False

    # ── lockdown (exfiltration guard) ─────────────────────────────────
    # Once a tool reports it returned sensitive data, the run may only make
    # observations — every action is denied for the rest of the run, so the
    # data cannot leave through another tool. Honours declarations by
    # default and detects nothing; pass a LockdownPolicy to add detection,
    # or False to disable. See shipit_agent.lockdown.
    lockdown: Any = None

    # ── automatic delegation ──────────────────────────────────────────
    # Reach for sub-agents without being asked: guarantee a `sub_agent` tool
    # exists, and when a task carries delegation signals (a per-item verb, an
    # enumerated work list, a wide sweep) append a directive naming what was
    # detected. The model still decides — it decides with the tool present
    # and the case put plainly. Off by default: every delegation is a real
    # agent loop with real calls. `True`, a DelegationPolicy, or a dict of
    # its fields. See shipit_agent.delegation.
    delegation: Any = None

    # ── self-healing tool calls ───────────────────────────────────────
    # Promote tool calls that small models emit as TEXT (<tool_call> tags,
    # fenced JSON, bare call-shaped JSON) into structured calls. Response-
    # side only; only declared tool names qualify. See tool_healing.py.
    heal_tool_calls: bool = True

    # ── project / file tools ──────────────────────────────────────────
    project_root: str | Path = "/tmp"

    # ── workspace (v1.0.14) ───────────────────────────────────────────
    # Auto-load SHIPIT.md / AGENTS.md project instructions into the system
    # prompt, and expand `/slash` commands from .shipit/commands/ on run().
    auto_project_memory: bool = True

    # ── skills (see docs/guides/skills.md) ────────────────────────────
    skill_registry: SkillRegistry | None = None  # pre-built registry
    skill_source: str | Path | None = DEFAULT_SKILLS_PATH  # catalog file
    auto_use_skills: bool = True  # prompt-based matching
    auto_project_skills: bool = True  # discover project-local SKILL.md files
    skills: list[SkillLike] = field(default_factory=list)  # always-on skills
    default_skill_ids: list[str] = field(default_factory=list)
    skill_match_limit: int = 3  # max auto-matched

    # ── internal: handle to the in-flight runtime (for cancel()) ──────
    _active_runtime: Any = field(default=None, repr=False, compare=False)
    # The sub_agent built for `delegation=`, kept so its thread pool is
    # created once per agent rather than once per run.
    _auto_sub_agent: Any = field(default=None, repr=False, compare=False)

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Cancel the in-flight ``run()`` / ``stream()`` (thread-safe).

        The loop stops at its next checkpoint — before the next LLM call or
        tool execution — emits ``run_cancelled``, and returns normally with
        whatever was produced so far. Call from another thread (e.g. a
        keyboard handler) while the agent is working; no-op when idle.
        """
        runtime = self._active_runtime
        if runtime is not None:
            runtime.cancel()

    def clone(self, **changes: Any) -> "Agent":
        """Copy this agent with selected configuration overrides.

        Mutable configuration containers are copied, while LLMs and durable
        stores are intentionally shared unless explicitly replaced.
        """
        from dataclasses import replace

        defaults = {
            "tools": list(self.tools),
            "mcps": list(self.mcps),
            "metadata": dict(self.metadata),
            "history": list(self.history),
            "skills": list(self.skills),
            "default_skill_ids": list(self.default_skill_ids),
        }
        defaults.update(changes)
        return replace(self, **defaults)

    def as_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        session_id: str | None = None,
        stream_events: bool = True,
    ) -> Any:
        """Expose this agent as a specialist tool for another agent."""
        from shipit_agent.tools.agent_tool import AgentTool

        return AgentTool(
            agent=self,
            name=name or self.name,
            description=description or self.description or f"Delegate to {self.name}.",
            session_id=session_id,
            stream_events=stream_events,
        )

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

        # Auto-load SHIPIT.md / AGENTS.md project instructions into the prompt.
        if self.auto_project_memory:
            from shipit_agent.workspace import load_project_memory

            memory = load_project_memory(self.project_root)
            if memory and memory not in self.prompt:
                self.prompt = f"{self.prompt}\n\n{memory}"

        # Build the skill registry from the catalog file if not supplied.
        if self.skill_registry is None and self.skill_source:
            skill_path = Path(self.skill_source)
            if skill_path.exists():
                self.skill_registry = FileSkillRegistry(skill_path)

        # Local SKILL.md files use the standard SKILL.md convention.
        # They override packaged entries with the same id so repository rules
        # remain authoritative without copying the full catalog.
        if self.auto_project_skills:
            from shipit_agent.skills import discover_project_skills

            local_skills = discover_project_skills(self.project_root)
            if local_skills and self.skill_registry is None:
                self.skill_registry = SkillRegistry()
            for skill in local_skills:
                self.skill_registry.register(skill)

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
        optimized: bool = False,
        **kwargs: Any,
    ) -> "Agent":
        """Build an Agent that ships with the full built-in tool catalogue.

        Creates all 50+ built-in tools (file ops, web search, bash, code
        execution, connectors, reasoning helpers, etc.) and merges them
        with any custom ``tools`` the caller provides.

        Set ``optimized=True`` for a token-efficient long-running setup:
        code mode exposes the large tool catalog progressively, context
        compaction uses the selected model's known window, and the default
        iteration budget increases to eight. Explicit caller values win.

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
        if optimized:
            from shipit_agent.compaction import get_model_limits

            kwargs.setdefault("code_mode", True)
            kwargs.setdefault(
                "context_window_tokens",
                get_model_limits(getattr(llm, "model", None)).context_window,
            )
            kwargs.setdefault("max_iterations", 8)
            kwargs.setdefault("max_tool_output_chars", 16_000)
            kwargs.setdefault("max_tool_output_group_chars", 48_000)
            kwargs.setdefault("parallel_tool_execution", True)
            kwargs.setdefault("max_tool_concurrency", 6)
            kwargs.setdefault("progress_summaries", True)
            kwargs.setdefault("persist_large_tool_outputs", True)
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

    @classmethod
    def for_project(
        cls,
        *,
        llm: Any,
        project_root: str | Path = ".",
        apply_env: bool = False,
        optimized: bool = False,
        **kwargs: Any,
    ) -> "Agent":
        """Build a workspace-aware agent rooted at a repo (the SHIPIT Workspace).

        Loads ``.shipit/settings.json`` (permissions + env), auto-attaches the
        full builtin tool catalogue, picks up ``SHIPIT.md`` / ``AGENTS.md``
        project instructions, and enables ``/slash`` commands from
        ``.shipit/commands/``. Point it at a directory and it just works::

            agent = Agent.for_project(
                llm=llm, project_root="/my/repo", optimized=True
            )
            chat = agent.chat_session(session_id="main")
            chat.send("/review src/app.py")
            chat.send("Now fix the issues you found")

        Optimized project agents persist sessions and long-term memory under
        ``.shipit/`` by default, so recreating the agent and reusing the same
        session id resumes the conversation. Explicit stores always win.
        """
        from shipit_agent.workspace import load_settings

        settings = load_settings(project_root)
        if apply_env:
            settings.apply_env()
        # Settings provide permissions unless the caller passed their own.
        if "permissions" not in kwargs and "permission_mode" not in kwargs:
            engine = settings.to_permission_engine()
            if engine is not None:
                kwargs["permissions"] = engine
        if optimized:
            from shipit_agent.stores import FileMemoryStore, FileSessionStore

            state_root = Path(project_root) / ".shipit"
            if "session_store" not in kwargs:
                kwargs["session_store"] = FileSessionStore(state_root / "sessions")
            if "memory_store" not in kwargs:
                kwargs["memory_store"] = FileMemoryStore(state_root / "memory.json")
        return cls.with_builtins(
            llm=llm,
            project_root=str(project_root),
            optimized=optimized,
            **kwargs,
        )

    @classmethod
    def for_role(
        cls,
        role: str,
        *,
        llm: Any,
        registry: Any = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> "Agent":
        """Build a ready-to-run agent from a prebuilt role definition.

        One line to a sector specialist — finance, marketing, engineering,
        design, research, sales, support, and 40+ more from the built-in
        :class:`~shipit_agent.agents.AgentRegistry`::

            agent = Agent.for_role("finance-analyst", llm=llm)
            agent = Agent.for_role("marketing-writer", llm=llm)
            agent = Agent.for_role("researcher", llm=llm)

        The definition's role/goal/backstory/prompt become the system
        prompt, its ``tools`` list selects the matching built-ins (plus any
        extra ``tools`` you pass), and ``max_iterations`` is applied.
        Unknown role ids raise ``ValueError`` listing close matches.
        """
        from shipit_agent.agents.registry import AgentRegistry
        from shipit_agent.builtins import get_builtin_tools

        reg = registry or AgentRegistry.default()
        definition = reg.get(role)
        if definition is None:
            near = [d.id for d in reg.search(role)][:5]
            hint = f" Did you mean: {', '.join(near)}?" if near else ""
            raise ValueError(f"Unknown role '{role}'.{hint}")

        sections = [
            f"You are {definition.name}. {definition.role}.",
            f"Goal: {definition.goal}." if definition.goal else "",
            definition.backstory,
            definition.prompt,
        ]
        prompt = "\n\n".join(s for s in sections if s)

        project_root = str(kwargs.pop("project_root", "."))
        builtin_tools = get_builtin_tools(
            llm=llm,
            project_root=project_root,
        )
        wanted = set(definition.tools)
        selected = (
            [t for t in builtin_tools if getattr(t, "name", None) in wanted]
            if wanted
            else list(builtin_tools)
        )
        supplied_metadata = dict(kwargs.pop("metadata", {}) or {})
        return cls(
            llm=llm,
            prompt=kwargs.pop("prompt", prompt),
            tools=[*selected, *(tools or [])],
            name=definition.id,
            description=definition.role,
            project_root=project_root,
            max_iterations=kwargs.pop("max_iterations", definition.max_iterations),
            metadata={
                "role": definition.id,
                "category": definition.category,
                **supplied_metadata,
            },
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

    def _delegation_policy(self) -> Any:
        from shipit_agent.delegation import coerce_delegation

        return coerce_delegation(self.delegation)

    def _delegation_warranted(self, user_prompt: str) -> bool:
        """Does this task look like sub-agent work?

        Explicit `tools=[SubAgentTool()]` is unaffected — that is a caller
        deciding, and this only governs what `delegation=` injects.
        """
        policy = self._delegation_policy()
        if policy is None:
            return False
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            return False
        try:
            return bool(policy.assess(user_prompt, llm=self.llm))
        except Exception:  # noqa: BLE001
            # An assessor that fails must not silently remove a capability.
            return True

    def _delegated_prompt(self, user_prompt: str) -> str:
        """The task with a delegation directive, when it warrants one.

        Appended to the *task*, not the system prompt. Measured against Gemma
        4 with three reports to summarize: in the system prompt it delegated
        zero times; the same text on the task, six. A small model reads the
        system prompt as background and the task as instructions.
        """
        policy = self._delegation_policy()
        if policy is None or not isinstance(user_prompt, str):
            return user_prompt
        return policy.apply(user_prompt, llm=self.llm)

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
        if self.code_mode:
            # Code mode supplies its own two tools: without describe_binding
            # the agent can see `env` in its prompt but cannot learn any
            # binding's API, and without execute_code it cannot call one.
            from shipit_agent.tools.describe_binding import DescribeBindingTool
            from shipit_agent.tools.execute_code import ExecuteCodeTool

            effective.setdefault("execute_code", ExecuteCodeTool())
            effective.setdefault("describe_binding", DescribeBindingTool())

        # An agent told to delegate needs something to delegate *to* — but
        # only for a task worth delegating. `delegation=` used to inject
        # `sub_agent` on every turn, so "look for the latest AI news" was
        # answered by spawning three research children instead of running
        # one web search: a tool on the table gets used, and a weaker model
        # reaches for the most impressive one.
        #
        # The policy already judges each task, because the directive depends
        # on it. Asking it here costs nothing extra (the assessment is
        # cached per task) and makes the toolbox match the advice.
        policy = self._delegation_policy()
        if policy is not None and not self._delegation_warranted(user_prompt):
            policy = None
        if policy is not None and "sub_agent" not in effective:
            if self._auto_sub_agent is None:
                self._auto_sub_agent = policy.build_tool(
                    self.llm, list(effective.values())
                )
            if self._auto_sub_agent is not None:
                effective["sub_agent"] = self._auto_sub_agent

        if not selected_skills:
            tools_list = list(effective.values())
            if self.verifier is not None and hasattr(self.verifier, "wrap_tools"):
                tools_list = self.verifier.wrap_tools(tools_list)
            return tools_list

        # Resolve skill-linked tools from the builtin map and merge in.
        builtin_tool_map = get_builtin_tool_map(
            llm=self.llm,
            project_root=str(self.project_root),
        )
        for tool_name in tool_names_for_skills(selected_skills):
            tool = builtin_tool_map.get(tool_name)
            if tool is not None:
                effective[tool_name] = tool
        tools_list = list(effective.values())
        # If a verifier is configured, wrap every tool so the verifier sees
        # each proposed call before it executes. The wrapper is transparent
        # to the runtime — same name/schema/run() surface as the inner tool.
        if self.verifier is not None and hasattr(self.verifier, "wrap_tools"):
            tools_list = self.verifier.wrap_tools(tools_list)
        return tools_list

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

    def _runtime_skill_metadata(
        self, selected_skills: list[Skill]
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        """Merge native skills with capabilities selected by a host application.

        A host may own skill authorization and prompt injection itself. It can
        report those already-applied skills through ``metadata`` without asking
        Shipit to apply their prompts or tools a second time.
        """
        details: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for skill in selected_skills:
            details.append(
                {
                    "id": skill.id,
                    "name": skill.display_name or skill.name or skill.id,
                    "description": skill.description,
                    "category": skill.category,
                }
            )
            seen_ids.add(skill.id)
        external = self.metadata.get("selected_skills", [])
        if isinstance(external, list):
            for item in external:
                if not isinstance(item, dict):
                    continue
                skill_id = str(item.get("id", "")).strip()
                if not skill_id or skill_id in seen_ids:
                    continue
                details.append(
                    {
                        "id": skill_id,
                        "name": str(item.get("name") or skill_id),
                        "description": str(item.get("description") or ""),
                        "category": str(item.get("category") or ""),
                    }
                )
                seen_ids.add(skill_id)

        tool_names = self._skill_tool_names(selected_skills)
        for name in self.metadata.get("used_skill_tools", []) or []:
            value = str(name).strip()
            if value and value not in tool_names:
                tool_names.append(value)
        return [item["id"] for item in details], tool_names, details

    def _effective_max_iterations(self, selected_skills: list[Skill]) -> int:
        """Auto-boost iteration budget when skills inject extra tools.

        Skills bring additional tools that the agent needs more turns to
        use effectively. When the caller left ``max_iterations`` at the
        default (12), we raise it to 16 so the agent can complete multi-step
        skill-driven workflows without cutting off early.

        An explicit override (a value other than the default 12) is respected.
        """
        if selected_skills and self.max_iterations <= 12:
            return max(16, self.max_iterations)
        return self.max_iterations

    def _effective_permissions(self) -> Any:
        """Resolve the permission engine for this run.

        An explicit ``permissions`` spec (engine / dict / mode string) wins and
        carries its own mode. Otherwise, if ``permission_mode`` is non-default
        or a ``permission_callback`` is set, build an engine from the mode.
        A ``permission_callback`` is attached when the engine has none.
        """
        from shipit_agent.permissions import PermissionEngine, coerce_permissions

        engine = coerce_permissions(self.permissions)
        if engine is None and (
            self.permission_mode != "default" or self.permission_callback is not None
        ):
            engine = PermissionEngine(mode=self.permission_mode)  # type: ignore[arg-type]
        if (
            engine is not None
            and self.permission_callback is not None
            and (engine.callback is None)
        ):
            engine.callback = self.permission_callback
        return engine

    def plan(self, user_prompt: str, **kwargs: Any) -> AgentResult:
        """Run in read-only **plan mode** — propose a plan without acting.

        Mutating/unknown tools are denied so the agent researches with
        read-only tools and writes a step-by-step plan instead of taking
        action. Returns an :class:`AgentResult` whose ``output`` is the plan.
        """
        import dataclasses

        from shipit_agent.permissions import PermissionEngine

        planner = dataclasses.replace(
            self,
            permission_mode="plan",
            permissions=PermissionEngine(
                mode="plan", callback=self.permission_callback
            ),
        )
        return planner.run(user_prompt, **kwargs)

    # ──────────────────────────────────────────────────────────────────
    # Run (synchronous)
    # ──────────────────────────────────────────────────────────────────

    def _expand_slash_command(self, user_prompt: str) -> str:
        """Expand a ``/command`` from ``.shipit/commands/``; else pass through."""
        if not isinstance(user_prompt, str) or not user_prompt.startswith("/"):
            return user_prompt
        from shipit_agent.workspace import expand_command

        expanded = expand_command(self.project_root, user_prompt)
        return expanded if expanded is not None else user_prompt

    def _user_content_blocks(
        self,
        prompt_text: str,
        images: list[str] | None,
        files: list[str] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Content blocks for a user turn with attachments, or None.

        None keeps every existing caller on the exact string path they had —
        blocks appear only when the turn actually carries attachments.
        """
        if not images and not files and self.media_parser is None:
            return None
        blocks: list[dict[str, Any]] | None = None
        if self.media_parser is not None:
            from shipit_agent.multimodal import build_multimodal_message

            try:
                parsed = self.media_parser.parse(prompt_text)
                blocks = list(build_multimodal_message(parsed).get("content") or [])
            except Exception:
                logger.warning("media_parser failed; sending prompt as text only")
                blocks = None
        if blocks is None:
            blocks = [{"type": "text", "text": prompt_text}]
        base_block_count = len(blocks)
        if files:
            from shipit_agent.multimodal.builder import file_blocks_from

            for file in files:
                blocks.extend(file_blocks_from(file))
        if images:
            from shipit_agent.multimodal.builder import image_block_from

            blocks.extend(image_block_from(image) for image in images)
        nothing_attached = len(blocks) == base_block_count and all(
            isinstance(b, dict) and b.get("type") == "text" for b in blocks
        )
        return None if nothing_attached else blocks

    def run(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
        output_schema: Any = None,
        max_validation_retries: int = 2,
    ) -> AgentResult:
        """Execute the agent loop and return the final result.

        ``images`` attaches pictures to this turn — each entry may be an
        ``http(s)`` URL, a local file path, or a base64/data: payload
        (needs a vision-capable model). ``files`` attaches documents: text,
        markdown and code files are inlined (portable to every provider);
        PDFs ride as native document blocks where the provider reads PDF.
        With ``Agent(media_parser=...)`` set, inline references in the
        prompt (``[https://…/x.png]``, ``![alt](url)``) attach automatically.

        Steps:
        1. Optionally append structured output schema instructions.
        2. Compute selected skills once — reused for prompt, tools, metadata.
        3. Build the ``AgentRuntime`` with effective prompt, tools, and
           boosted iteration budget.
        4. Run the loop: LLM call → tool execution → repeat.
        5. Optionally parse the output against ``output_schema``.
        6. Return ``AgentResult`` with output, messages, events, and metadata.
        """
        user_prompt = self._delegated_prompt(self._expand_slash_command(user_prompt))
        # Append schema instructions to the USER prompt (not system prompt)
        # so the model can still use tools normally and only formats the
        # final answer as JSON. Bedrock returns empty content when schema
        # instructions pollute the system prompt.
        effective_user_prompt = user_prompt
        response_format: dict[str, Any] | None = None
        if output_schema:
            from shipit_agent.structured import (
                build_schema_prompt,
                schema_to_response_format,
            )

            effective_user_prompt = user_prompt + build_schema_prompt(output_schema)
            # Native response_format is applied by the runtime only on the
            # tool-less final turn; the prompt instruction above still drives
            # the format on providers/mid-loop, and validate_with_retry below
            # remains the safety net.
            response_format = schema_to_response_format(output_schema) or None

        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(
            user_prompt, selected_skills=selected_skills
        )
        skill_ids, skill_tool_names, skill_details = self._runtime_skill_metadata(
            selected_skills
        )

        runtime = self._active_runtime = AgentRuntime(
            llm=self.llm,
            decision_llm=self.decision_llm,
            progress_summaries=self.progress_summaries,
            reminder=self.reminder,
            evict_prior_tool_outputs=self.evict_prior_tool_outputs,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
                "used_skills": skill_ids,
                "used_skill_tools": skill_tool_names,
                "selected_skills": skill_details,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self._resolved_trace_store(),
            trace_id=self.trace_id,
            max_iterations=self._effective_max_iterations(selected_skills),
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
            parallel_tool_execution=self.parallel_tool_execution,
            max_tool_concurrency=self.max_tool_concurrency,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            max_tool_output_chars=self.max_tool_output_chars,
            max_tool_output_group_chars=self.max_tool_output_group_chars,
            tool_output_dir=(
                str(Path(self.project_root) / ".shipit" / "tool-results")
                if self.persist_large_tool_outputs
                else None
            ),
            replan_interval=self.replan_interval,
            permissions=self._effective_permissions(),
            guardrails=self.guardrails,
            heal_tool_calls=self.heal_tool_calls,
            approvals=self.approvals,
            code_mode=self.code_mode,
            deferred_tools=self.deferred_tools,
            lockdown=self.lockdown,
            response_format=response_format,
        )
        state, response = runtime.run(
            effective_user_prompt,
            user_content=self._user_content_blocks(
                effective_user_prompt, images, files
            ),
        )

        # Optionally parse structured output from the LLM response, with
        # validation-retry: if the first parse fails, send the error back
        # to the same LLM (no tools) and ask for a corrected response.
        # Cheap fix-it round trip; only fires when the first parse fails.
        parsed = None
        if output_schema and response.content:
            from shipit_agent.structured_output import validate_with_retry

            parsed, retry_text, attempts, attempt_log = validate_with_retry(
                llm=self.llm,
                raw_text=response.content,
                schema=output_schema,
                history=state.messages,
                max_retries=max_validation_retries,
            )
            if parsed is None:
                logger.warning(
                    "output_schema parsing failed after %d attempts. Last error: %s — raw: %s",
                    attempts,
                    attempt_log[-1]["error"] if attempt_log else "unknown",
                    response.content[:500],
                )
            elif attempts > 1:
                # Retry succeeded — surface the corrected text as the output.
                logger.info(
                    "output_schema parsed on attempt %d (after %d failures)",
                    attempts,
                    attempts - 1,
                )
                response.content = retry_text
        elif output_schema and not response.content:
            logger.warning(
                "output_schema was set but LLM returned empty content — "
                "parsed will be None. Try increasing max_iterations."
            )

        rag_sources = self.rag.end_run() if self.rag is not None else []

        # Attach skill metadata so callers can see what was used.
        result_metadata = dict(response.metadata)
        for key in ("gave_up", "give_up_reason", "give_up_needs"):
            if key in runtime.metadata:
                result_metadata[key] = runtime.metadata[key]
        result_metadata["used_skills"] = skill_ids
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

    def run_live(
        self,
        user_prompt: str,
        *,
        file: Any = None,
        style: str = "auto",
        detail: bool = False,
    ) -> str:
        """Run with a live, streaming display and return the answer.

        Tokens print as they're generated (when the LLM adapter streams),
        tool calls appear as ⚙ cards with args, status, and duration, and a
        one-line summary closes the run::

            agent.run_live("Close Q2 and hand me the workbook.")
            # ⚙ build_document(kind="xlsx", …) …
            # ⚙ build_document ✓ 228ms
            #   └ Created XLSX 'Q2 Close' → q2_close.xlsx
            # The workbook is ready — net income formula included.
            # ✔ done · 1 tool call

        Pass ``file=`` to redirect output (any object with ``write``).
        Returns the final answer text; use :meth:`run` when you need the
        full :class:`AgentResult`.

        ``style="tree"`` renders the *shape* of the run instead — every call
        named with its status, decisions marked where they happened. Good for
        debugging and for explaining what an agent did.

        ``style="modern"`` switches to the Narrator — human verbs, collapsed
        work runs, and a tokens/cost footer (see
        ``docs/design/modern-agent-upgrade.md``)::

            agent.run_live("Which accounts are at risk?", style="modern")
            # ⌕ Read 3 files ›
            #   Enterprise Accounts · Open Tickets · Usage by Account
            #
            # Three I would put on your list: …
            #                                    18,240 tokens · $0.12
        """
        if style not in _LIVE_STYLES:
            # A typo used to render the default view silently, which reads as
            # "the style I asked for does nothing".
            raise ValueError(
                f"Unknown style {style!r}. Valid styles: "
                f"{', '.join(sorted(_LIVE_STYLES))}."
            )
        if style == "tree":
            from shipit_agent.narrate import TreeRenderer

            renderer = TreeRenderer(
                file=file, model=getattr(self.llm, "model", None), detail=detail
            )
        elif style == "modern":
            from shipit_agent.narrate import NarratorRenderer

            renderer = NarratorRenderer(
                file=file, model=getattr(self.llm, "model", None)
            )
        else:
            from shipit_agent.activity import StreamRenderer

            renderer = StreamRenderer(file=file, style=style)
        output = ""
        for event in self.stream(user_prompt):
            renderer.feed(event)
            if event.type == "run_completed":
                output = str(event.payload.get("output", "") or "")
        renderer.close()
        return output

    def stream(
        self,
        user_prompt: str,
        *,
        images: list[str] | None = None,
        files: list[str] | None = None,
    ):
        """Stream agent events as they happen.

        Same pipeline as :meth:`run`, but yields :class:`AgentEvent` objects
        instead of blocking. This is the low-level feed — every event, in
        order::

            for event in agent.stream("Fix the failing test"):
                if event.type == "text_delta":
                    print(event.payload["chunk"], end="", flush=True)

        ``images`` and ``files`` attach media to the turn, exactly as in
        :meth:`run` — URLs, local paths, or base64 for images; text/markdown/
        code files inlined, PDFs as document blocks::

            for event in agent.stream("What changed?",
                                      images=["diagram.png"], files=["spec.pdf"]):
                ...

        Most callers want one of the three wrappers built on it instead:

        - :meth:`run_live` — the finished transcript, printed for you
        - :meth:`narrate` — the same rows as objects, for your own UI
        - ``shipit_agent.streaming.sse`` — framed for a browser, with each
          event labelled canonical or provisional

        Every event carries ``type``, ``message``, ``payload`` and
        ``timestamp``; see :data:`shipit_agent.models.EventType` for the
        vocabulary.
        """
        user_prompt = self._delegated_prompt(self._expand_slash_command(user_prompt))
        if self.rag is not None:
            self.rag.begin_run()

        # Compute skills once and reuse across prompt, tools, and metadata.
        selected_skills = self._selected_skills(user_prompt)
        effective_tools = self._effective_tools(
            user_prompt, selected_skills=selected_skills
        )
        skill_ids, skill_tool_names, skill_details = self._runtime_skill_metadata(
            selected_skills
        )

        runtime = self._active_runtime = AgentRuntime(
            llm=self.llm,
            decision_llm=self.decision_llm,
            progress_summaries=self.progress_summaries,
            reminder=self.reminder,
            evict_prior_tool_outputs=self.evict_prior_tool_outputs,
            prompt=self._effective_prompt(user_prompt),
            tools=effective_tools,
            mcps=self.mcps,
            metadata={
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
                "used_skills": skill_ids,
                "used_skill_tools": skill_tool_names,
                "selected_skills": skill_details,
            },
            history_messages=list(self.history),
            memory_store=self.memory_store,
            session_store=self.session_store,
            session_id=self.session_id,
            trace_store=self._resolved_trace_store(),
            trace_id=self.trace_id,
            max_iterations=self._effective_max_iterations(selected_skills),
            retry_policy=self.retry_policy,
            router_policy=self.router_policy,
            credential_store=self.credential_store,
            parallel_tool_execution=self.parallel_tool_execution,
            max_tool_concurrency=self.max_tool_concurrency,
            hooks=self.hooks,
            context_window_tokens=self.context_window_tokens,
            max_tool_output_chars=self.max_tool_output_chars,
            max_tool_output_group_chars=self.max_tool_output_group_chars,
            tool_output_dir=(
                str(Path(self.project_root) / ".shipit" / "tool-results")
                if self.persist_large_tool_outputs
                else None
            ),
            replan_interval=self.replan_interval,
            permissions=self._effective_permissions(),
            guardrails=self.guardrails,
            heal_tool_calls=self.heal_tool_calls,
            approvals=self.approvals,
            code_mode=self.code_mode,
            deferred_tools=self.deferred_tools,
            lockdown=self.lockdown,
        )
        user_content = self._user_content_blocks(user_prompt, images, files)
        for event in runtime.stream(user_prompt, user_content=user_content):
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

    def narrate(self, user_prompt: str):
        """Stream *transcript rows* rather than raw events.

        The same collapsing the terminal renderer does — verbs, work runs,
        approvals, sub-agent activity — handed to you as objects so you can
        render them however you like::

            for row in agent.narrate("Which accounts are at risk?"):
                match row:
                    case ProseRow(text):        print(text)
                    case WorkRow(group):        print("·", group.label)
                    case ApprovalRow() as a:    prompt_user(a)

        A row is yielded when it settles — prose closes a work run, and a
        work run closes prose — so you never have to decide when a group is
        finished. Raw events are still there via :meth:`stream` if you need
        them.
        """
        from shipit_agent.narrate.grouping import WorkRunAccumulator

        accumulator = WorkRunAccumulator()
        for event in self.stream(user_prompt):
            for row in accumulator.feed(event):
                yield row
        for row in accumulator.finish():
            yield row

    def stream_sse(self, user_prompt: str):
        """Stream the run as Server-Sent Events, ready for the wire::

            @app.get("/run")
            def run():
                return StreamingResponse(
                    agent.stream_sse(prompt), media_type="text/event-stream"
                )

        Opens with a ``stream_hello`` carrying this process's generation, so a
        reconnecting client knows whether to keep what it already drew, and
        closes with ``[DONE]``. See :mod:`shipit_agent.streaming`.
        """
        from shipit_agent.streaming import hello_frame, sse

        yield sse(hello_frame())
        sequence = 0
        for event in self.stream(user_prompt):
            sequence += 1
            yield sse(event, sequence=sequence)
        yield "event: done\ndata: [DONE]\n\n"


    def _resolved_trace_store(self) -> Any:
        """The trace store to run with, honouring ``observability``.

        Import failures and misconfiguration are swallowed on purpose:
        observability that can stop a run is worse than none, because the
        run is the thing the user actually asked for.
        """
        if self.trace_store is not None:
            return self.trace_store
        if self.observability is False:
            return None
        try:
            from shipit_agent.tracing_exporters import WatcherExporter

            if self.observability != "auto":
                return WatcherExporter()
            from shipit_watcher import get_config

            return WatcherExporter() if get_config().is_active else None
        except Exception:
            logger.debug("shipit-watcher not available", exc_info=True)
            return None

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
