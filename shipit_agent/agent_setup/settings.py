"""Everything you can configure on an :class:`~shipit_agent.agent.Agent`.

:class:`AgentSettings` holds the agent's public fields, each documented where
it is declared. :class:`~shipit_agent.agent.Agent` inherits them, so
``Agent(llm=..., tools=[...])`` takes exactly these keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.core.policies import RetryPolicy, RouterPolicy
from shipit_agent.integrations import CredentialStore
from shipit_agent.observability.tracing import TraceStore
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT
from shipit_agent.skills import SkillRegistry
from shipit_agent.stores import MemoryStore, SessionStore

from .skill_refs import DEFAULT_SKILLS_PATH as DEFAULT_SKILLS_PATH
from .skill_refs import SkillLike as SkillLike



@dataclass(slots=True)
class AgentSettings:
    """The agent's configuration: model, tools, skills, limits, safety and stores."""

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
    #: Tool names that must execute before this run may finish. The runtime
    #: advertises only these tools and uses native required-tool mode first,
    #: then resets to automatic selection after they have run.
    required_tools: list[str] = field(default_factory=list)
    #: Require at least one available tool on the first model step, without
    #: constraining which one. Mirrors provider ``tool_choice="required"``.
    require_tool_call: bool = False
    #: Stop a provider that ignores required tool choice from spending its
    #: whole output budget narrating a call. The partial prose is discarded and
    #: the bounded recovery step receives the same required tool contract.
    max_required_tool_text_chars: int = 2_048
    #: Optional provider-neutral circuit breaker for one completion's visible
    #: text. Zero leaves the provider's token limit authoritative. Hosts can
    #: set a smaller bound for interactive agents where a runaway completion
    #: must not consume an entire large output allowance.
    max_completion_text_chars: int = 0
    #: Provider-neutral circuit breaker for one structured tool call's JSON
    #: arguments. This bounds runaway generations before they reach a tool;
    #: increase it for tools that intentionally accept very large documents.
    max_tool_argument_chars: int = 65_536
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
    #: Most model steps a run may take. ``None`` (the default) means no limit:
    #: the run ends when the model answers without calling a tool, as in the
    #: Claude Agent SDK. Any fixed count cuts some real task off mid-way; cap
    #: spend with ``max_budget_usd`` instead, or set a number here.
    max_iterations: int | None = None
    #: The Claude Agent SDK's name for ``max_iterations``; set either one.
    max_turns: int | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    #: Used when the model fails after its retries: a model id, ids separated
    #: by commas, an adapter, or a list of them (see ``llms/fallback.py``).
    fallback_model: Any = None
    router_policy: RouterPolicy = field(default_factory=RouterPolicy)
    #: Run a response's tool calls concurrently when every one is read-only.
    #: Writes and unknown tools always run one at a time, in order.
    parallel_tool_execution: bool = True
    # None means no cap; otherwise bound concurrent local tool calls per turn.
    max_tool_concurrency: int | None = None
    hooks: Any = None
    # Drop-in plugin packs: Plugin objects or catalog names. Each contributes
    # tools and lifecycle hooks, folded in at construction (see
    # shipit_agent.plugins). Left empty by default — zero cost when unused.
    plugins: list[Any] = field(default_factory=list)
    #: Hide tools whose declared dependency is missing (a CLI binary not on
    #: PATH, an unset env var, a failing ``check_fn``) so their schema never
    #: costs tokens and the model never wastes a turn calling something that
    #: cannot run. Only tools that *declare* requirements can be gated, so this
    #: is safe to leave on: a tool with no declaration is always kept.
    gate_unavailable_tools: bool = True
    # 0 = automatic model limit; positive = explicit limit; -1 = disabled.
    context_window_tokens: int = 0
    #: Clear old tool results from each request on long tasks (the history
    #: keeps them): True, or a ToolResultClearing. See context/tool_result_clearing.py.
    clear_tool_results: Any = None
    #: The fixed prompt prefix (system prompt + tool schemas) is sent on every
    #: call but lives outside ``messages``, so the compaction trigger under-counts
    #: the real prompt by this whole prefix unless it is told. A host that knows
    #: its prefix size can pass an estimate here to make compaction accurate from
    #: the first turn; leaving it 0 lets the token calibrator learn the gap over a
    #: few completions instead. Either way the calibrator corrects tokenizer drift.
    fixed_prefix_tokens: int = 0
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
    stream_queue_maxsize: int = 256
    cancel_on_stream_close: bool = True
    stream_join_timeout: float = 2.0

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
    #: A :class:`~shipit_agent.harness.Harness`: plugins and settings files.
    harness: Any = None
    #: Pre-approved calls, as SDK rules: ``"Read"``, ``"Bash(npm test *)"``.
    #: They approve; they do not restrict the other tools.
    allowed_tools: list[str] = field(default_factory=list)
    #: A bare name removes the tool from the run; a scoped rule such as
    #: ``"Bash(rm *)"`` denies matching calls in every permission mode.
    disallowed_tools: list[str] = field(default_factory=list)

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
    # Default "auto": above ten tools, keep nine core capabilities and a
    # discovery tool. discovery_priority on a tool overrides core ranking;
    # ties follow registration order. False opts out. Core tools keep schemas in
    # every request; everything else is listed by NAME only until
    # `tool_search` (or a direct call) loads it. Cuts the fixed per-step
    # schema cost to the working set. ``True`` defers everything outside
    # the core set; a list of names defers exactly those. Ignored when
    # ``code_mode`` is on (code mode collapses the catalogue its own way).
    deferred_tools: Any = "auto"
    # Pass deferral.DiscoveryPolicy(...) for initial schema-token/count budgets
    # and bounded session reuse. Auto uses 10 tools / ~4096 schema tokens.

    # ── lockdown (exfiltration guard) ─────────────────────────────────
    # Once a tool reports it returned sensitive data, the run may only make
    # observations — every action is denied for the rest of the run, so the
    # data cannot leave through another tool. Honours declarations by
    # default and detects nothing; pass a LockdownPolicy to add detection,
    # or False to disable. See shipit_agent.lockdown.
    lockdown: Any = None
    # Evidence-gated coding: refuse to finish a turn that edited code without
    # fresh passing tests (the verification ledger + verify-on-stop guard). Off
    # by default — it changes the loop's stop behaviour, so a caller opts in.
    verify_before_stop: bool = False

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
    #: Skills load on demand, as in Claude Code: the prompt lists each in one
    #: line and the model reads one with ``load_skill`` when it needs it.
    #: False restores keyword matching that injects whole skills.
    progressive_skills: bool = True
    #: List the library's packaged skill catalog too. Off by default: the
    #: catalog lists the project's own SKILL.md files and any registry you
    #: pass; packaged skills stay usable by id through ``skills=[...]``.
    advertise_packaged_skills: bool = False
    #: Named sub-agents, as in the Claude Agent SDK: ``{"reviewer": {
    #: "description": ..., "prompt": ..., "tools": [...], "model": ...}}``.
    #: Defining any gives the agent a ``sub_agent`` tool that lists them.
    agents: dict[str, Any] = field(default_factory=dict)
    #: Also read sub-agents from ``.shipit/agents/*.md`` and ``.claude/agents/*.md``.
    auto_project_agents: bool = True
    max_task_tokens: int | None = None  # soft per-run stop between model steps
    #: Stop a run, between steps, once its estimated cost reaches this many
    #: US dollars. Needs pricing data for the model; without it the run stops
    #: rather than spend unchecked.
    max_budget_usd: float | None = None
    # Soft stop across every run of this agent (or one chat session), checked
    # between steps. Clones start fresh; reset with reset_session_usage().
    max_session_tokens: int | None = None

    # ── rules (see shipit_agent/rules/) ───────────────────────────────
    # Durable behavioural policy (AGENTS.md house-style), scoped to paths/tools
    # and ordered by priority — the complement to skills' capability. Strings,
    # dicts, or Rule objects; discovered `.shipit/rules/*.md` are merged in when
    # auto_project_rules is on. Tools that ship their own `rules` surface only
    # when active.
    rules: list[Any] = field(default_factory=list)
    auto_project_rules: bool = True
