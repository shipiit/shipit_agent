"""Letting the existing ``Agent`` drive the new run loop.

``shipit_agent.agent.Agent`` is the product: 57 fields and twenty methods that
callers depend on — ``clone``, ``as_tool``, ``with_builtins``, ``for_project``,
``plan``, ``narrate``, ``doctor``, ``chat_session``, and ``run`` with images,
files and an output schema. Replacing it to gain a better loop would trade a
large public surface for a small one, which is a regression however good the
loop is.

So the loop plugs in underneath instead. This module reads an existing ``Agent``
and produces the :class:`~shipit_agent.graph.RunSpec` the new graph needs, so
``Agent.run`` and ``Agent.stream`` can delegate without changing a single field
name. Adoption is incremental: build a spec, run it, compare, keep whichever is
better — and the old runtime stays until it is not needed.

The mapping is not always one to one, and where it is not, this module says so
rather than guessing. ``unmapped()`` returns every field whose behaviour the new
loop does not yet reproduce, so a migration is a checklist rather than a
discovery process.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shipit_agent.graph import RunSpec
from shipit_agent.mcp_bridge import MCPBridge
from shipit_agent.prefix_rules import collect_tool_rules, render_rules
from shipit_agent.usage import TierPolicy, UsageLedger

logger = logging.getLogger(__name__)

__all__ = ["spec_from_agent", "unmapped", "MAPPING", "NOT_YET_MAPPED"]


#: Existing field → what now provides it. The value is the machinery, not a
#: rename: several fields are satisfied by a different mechanism entirely.
MAPPING: dict[str, str] = {
    "llm": "RunSpec.llm",
    "prompt": "RunSpec.system_prompt (base only — skills no longer append here)",
    "tools": "RunSpec.tools",
    "mcps": "RunSpec.mcp via MCPBridge (lazy: described now, connected on call)",
    "history": "graph.messages, seeded before the run",
    "max_iterations": "RunSpec.max_iterations, overridable by a host parameter",
    "max_tool_output_chars": "RunSpec.max_tool_output_chars",
    "rules": "prefix_rules.render_rules, scoped by active tools",
    "auto_project_rules": "rules.loader.load_project_rules, rendered once per run",
    "skills": "always-apply primes; the rest reachable via load_skill",
    "default_skill_ids": "always-apply primes",
    "skill_registry": "RunSpec.skills — catalog in the prefix, bodies on demand",
    "auto_use_skills": "trigger-phrase priming, one of three trigger classes",
    "skill_match_limit": "SkillCaps.manual",
    "deferred_tools": "RunSpec.deferred_tools via discovery.DiscoveryState",
    "permission_callback": "RunSpec.approve",
    "permissions": "RunSpec.approve (policy evaluated by the caller)",
    "approvals": "RunSpec.approve + checkpoint.PendingApproval",
    "context_window_tokens": "capabilities.input_budget() when unset",
    "fixed_prefix_tokens": "PromptPrefix.approx_tokens(), measured not estimated",
    "session_id": "RunCheckpoint.session_id",
    "delegation": "subagents.SubagentTool, with usage attributed to the ledger",
}

#: Fields the new loop does not yet reproduce. Listed rather than silently
#: dropped: a migration that quietly loses a feature is worse than one that
#: refuses to start.
NOT_YET_MAPPED: dict[str, str] = {
    "decision_llm": "A cheaper model for routing decisions. The graph uses one model.",
    "progress_summaries": "Model-generated narration between steps.",
    "reminder": "Periodic re-injection of an instruction.",
    "evict_prior_tool_outputs": "Dropping earlier tool results from history.",
    "media_parser": "Auto-attaching images referenced inline in the prompt.",
    "rag": "Retrieval before the first turn.",
    "verifier": "End-of-run checking.",
    "verify_before_stop": "Blocking the final answer on verification.",
    "guardrails": "Input/output content policy.",
    "lockdown": "Escalating restriction after a violation.",
    "code_mode": "Model writes code that calls tools.",
    "heal_tool_calls": "Repairing malformed tool arguments.",
    "replan_interval": "Periodic replanning.",
    "router_policy": "Model selection per turn.",
    "retry_policy": "Superseded by llms.throttle, but not yet wired in.",
    "parallel_tool_execution": "The graph runs a batch sequentially.",
    "max_tool_concurrency": "Depends on parallel execution.",
    "hooks": "Lifecycle callbacks around LLM and tool calls.",
    "plugins": "Bundled tools and hooks folded in at construction.",
    "observability": "Trace export.",
    "trace_store": "Trace persistence.",
    "memory_store": "Superseded by tools.memory, but not the same interface.",
    "persist_large_tool_outputs": "Spilling large results to disk.",
    "max_tool_output_group_chars": "Per-batch output budget.",
    "gate_unavailable_tools": "Hiding tools whose dependency is missing.",
}


def _tool_names(tools: Iterable[Any]) -> list[str]:
    return [str(getattr(tool, "name", "")) for tool in tools if getattr(tool, "name", "")]


def _skills_of(agent: Any) -> list[Any]:
    """Every skill this agent can reach, from whichever source it uses."""
    found: list[Any] = []
    registry = getattr(agent, "skill_registry", None)
    if registry is not None:
        try:
            found.extend(list(registry))
        except TypeError:
            logger.debug("Skill registry is not iterable; skipping")
    for skill in getattr(agent, "skills", None) or ():
        if not isinstance(skill, str):
            found.append(skill)

    unique: dict[str, Any] = {}
    for skill in found:
        skill_id = str(getattr(skill, "id", "") or "")
        if skill_id:
            unique.setdefault(skill_id, skill)
    return sorted(unique.values(), key=lambda s: str(getattr(s, "id", "")))


def _always_apply(agent: Any, skills: list[Any], prompt: str) -> list[Any]:
    """Skills primed before the first turn: explicit, defaults, and triggers.

    Trigger matching stays as one of three paths rather than the only one. It
    costs no model turn when it hits, and when it misses ``load_skill`` still
    covers the case — including a need that only appears at iteration four,
    which trigger matching alone can never serve.
    """
    by_id = {str(getattr(s, "id", "")): s for s in skills}
    primed: dict[str, Any] = {}

    for reference in getattr(agent, "skills", None) or ():
        skill = by_id.get(reference) if isinstance(reference, str) else reference
        if skill is not None:
            primed.setdefault(str(getattr(skill, "id", "")), skill)

    for skill_id in getattr(agent, "default_skill_ids", None) or ():
        skill = by_id.get(str(skill_id))
        if skill is not None:
            primed.setdefault(str(skill_id), skill)

    if getattr(agent, "auto_use_skills", False) and prompt:
        lowered = prompt.lower()
        limit = int(getattr(agent, "skill_match_limit", 3) or 3)
        matched = 0
        for skill in skills:
            phrases = getattr(skill, "trigger_phrases", None) or []
            if any(str(p).lower() in lowered for p in phrases):
                primed.setdefault(str(getattr(skill, "id", "")), skill)
                matched += 1
                if matched >= limit:
                    break

    return [s for s in primed.values() if s is not None]


def _rules_block(agent: Any, tools: Iterable[Any]) -> str:
    """Rendered once, from the agent's rules plus any a tool ships itself."""
    rules = list(getattr(agent, "rules", None) or [])
    project = getattr(agent, "_project_rules", None)
    if project:
        try:
            rules.extend(list(project))
        except TypeError:
            logger.debug("Project rules are not iterable; skipping")
    rules.extend(collect_tool_rules(tools))
    return render_rules(rules, active_tools=_tool_names(tools))


def _mcp_bridge(agent: Any, max_eager_tools: int) -> MCPBridge | None:
    servers = list(getattr(agent, "mcps", None) or [])
    if not servers:
        return None
    bridge = MCPBridge(servers, max_eager_tools=max_eager_tools)
    bridge.attach()
    connect = getattr(agent, "mcp_connect", None)
    if callable(connect):
        bridge.connect = connect  # type: ignore[attr-defined]
    return bridge


def spec_from_agent(
    agent: Any,
    prompt: str = "",
    *,
    ledger: UsageLedger | None = None,
    tier_policy: TierPolicy | None = None,
    model: str = "",
    max_eager_mcp_tools: int = 12,
    compact: Callable[[list[Any]], list[Any] | None] | None = None,
) -> RunSpec:
    """Build a :class:`RunSpec` from an existing ``Agent``.

    Every field this reads keeps its current name and meaning. Nothing is
    invented: where the agent has no value, the spec's own default applies, and
    where the new loop has no equivalent, :func:`unmapped` names it.
    """
    tools = list(getattr(agent, "tools", None) or [])
    skills = _skills_of(agent)
    resolved_model = model or str(
        getattr(agent, "model", "") or getattr(getattr(agent, "llm", None), "model", "")
    )

    return RunSpec(
        llm=getattr(agent, "llm", None),
        model=resolved_model,
        # Base prompt only. Skill bodies used to be appended here, which moved
        # the prefix on every run and cost every cached token; they now arrive
        # as messages in the tail.
        system_prompt=str(getattr(agent, "prompt", "") or ""),
        rules=_rules_block(agent, tools),
        tools=tools,
        skills=skills,
        always_apply_skills=_always_apply(agent, skills, prompt),
        mcp=_mcp_bridge(agent, max_eager_mcp_tools),
        deferred_tools=[
            name
            for name in (getattr(agent, "deferred_tools", None) or [])
            if isinstance(name, str)
        ],
        model_parameters=dict(getattr(agent, "model_parameters", None) or {}),
        max_iterations=int(getattr(agent, "max_iterations", 12) or 12),
        max_tool_output_chars=int(getattr(agent, "max_tool_output_chars", 16_000) or 16_000),
        tier_policy=tier_policy,
        ledger=ledger or UsageLedger(),
        approve=getattr(agent, "permission_callback", None),
        compact=compact,
        should_cancel=getattr(agent, "_is_cancelled", None),
    )


def unmapped(agent: Any) -> dict[str, str]:
    """Which of this agent's configured features the new loop does not cover.

    Only fields actually set to something meaningful are reported — an agent
    that never enabled ``code_mode`` should not be told it is missing.
    """
    gaps: dict[str, str] = {}
    for field, note in NOT_YET_MAPPED.items():
        value = getattr(agent, field, None)
        if value in (None, False, 0, "", (), []):
            continue
        if field == "observability" and value == "auto":
            continue
        gaps[field] = note
    return gaps
