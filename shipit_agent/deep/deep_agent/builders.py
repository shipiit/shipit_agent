"""Ready-made DeepAgent constructors: with_builtins and for_project."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from shipit_agent.agent import DEFAULT_SKILLS_PATH
from shipit_agent.core.models import Message
from shipit_agent.core.policies import RetryPolicy, RouterPolicy
from shipit_agent.skills import Skill, SkillRegistry
from shipit_agent.stores import SessionStore

from ..goal_agent import Goal
from .prompt import DEEP_AGENT_PROMPT

if TYPE_CHECKING:
    from .factory import DeepAgent

class _DeepAgentBuilders:
    """Ready-made DeepAgent constructors: with_builtins and for_project."""

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        decision_llm: Any = None,
        progress_summaries: bool = False,
        prompt: str = DEEP_AGENT_PROMPT,
        name: str = "shipit-deep-agent",
        description: str = "A deep agent that plans, verifies, and uses a workspace.",
        metadata: dict[str, Any] | None = None,
        history: list[Message] | None = None,
        extra_tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        workspace_root: str = ".shipit_workspace",
        project_root: str | Path = "/tmp",
        web_search_provider: str = "duckduckgo",
        web_search_api_key: str | None = None,
        web_search_config: dict[str, Any] | None = None,
        rag: Any = None,
        memory: Any = None,
        memory_store: Any = None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        verify: bool = False,
        reflect: bool = False,
        reflect_threshold: float = 0.8,
        reflect_max_iterations: int = 3,
        goal: Goal | None = None,
        agents: Any = None,
        max_iterations: int = 8,
        parallel_tool_execution: bool = True,
        max_tool_concurrency: int | None = None,
        context_window_tokens: int = 0,
        max_tool_output_chars: int = 0,
        replan_interval: int = 0,
        retry_policy: RetryPolicy | None = None,
        router_policy: RouterPolicy | None = None,
        hooks: Any = None,
        trace_store: Any = None,
        trace_id: str | None = None,
        credential_store: Any = None,
        permission_mode: str = "default",
        permissions: Any = None,
        permission_callback: Any = None,
        guardrails: Any = None,
        approvals: Any = None,
        code_mode: bool = False,
        lockdown: Any = None,
        heal_tool_calls: bool = True,
        skill_registry: SkillRegistry | None = None,
        skill_source: str | Path | None = DEFAULT_SKILLS_PATH,
        auto_use_skills: bool = True,
        auto_project_skills: bool = True,
        skills: list[str | Skill] | None = None,
        default_skill_ids: list[str] | None = None,
        skill_match_limit: int = 3,
        **agent_kwargs: Any,
    ) -> "DeepAgent":
        """Build a DeepAgent that also bundles the full built-in tool catalogue."""
        return cls(
            llm=llm,
            decision_llm=decision_llm,
            progress_summaries=progress_summaries,
            name=name,
            description=description,
            prompt=prompt,
            metadata=metadata or {},
            history=list(history or []),
            extra_tools=list(extra_tools or []),
            mcps=list(mcps or []),
            workspace_root=workspace_root,
            project_root=project_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
            rag=rag,
            memory=memory,
            memory_store=memory_store,
            session_store=session_store,
            session_id=session_id,
            verify=verify,
            reflect=reflect,
            reflect_threshold=reflect_threshold,
            reflect_max_iterations=reflect_max_iterations,
            goal=goal,
            agents=agents,
            max_iterations=max_iterations,
            parallel_tool_execution=parallel_tool_execution,
            max_tool_concurrency=max_tool_concurrency,
            context_window_tokens=context_window_tokens,
            max_tool_output_chars=max_tool_output_chars,
            replan_interval=replan_interval,
            retry_policy=retry_policy,
            router_policy=router_policy,
            hooks=hooks,
            trace_store=trace_store,
            trace_id=trace_id,
            credential_store=credential_store,
            permission_mode=permission_mode,
            permissions=permissions,
            permission_callback=permission_callback,
            guardrails=guardrails,
            approvals=approvals,
            code_mode=code_mode,
            lockdown=lockdown,
            heal_tool_calls=heal_tool_calls,
            skill_registry=skill_registry,
            skill_source=skill_source,
            auto_use_skills=auto_use_skills,
            auto_project_skills=auto_project_skills,
            skills=list(skills or []),
            default_skill_ids=list(default_skill_ids or []),
            skill_match_limit=skill_match_limit,
            use_builtins=True,
            agent_kwargs=agent_kwargs,
        )

    @classmethod
    def for_project(
        cls,
        *,
        llm: Any,
        project_root: str | Path = ".",
        optimized: bool = True,
        **kwargs: Any,
    ) -> "DeepAgent":
        """Build a durable, token-efficient deep agent for one repository."""
        if optimized:
            from shipit_agent.context.compaction import get_model_limits
            from shipit_agent.stores import FileMemoryStore, FileSessionStore

            state_root = Path(project_root) / ".shipit"
            kwargs.setdefault(
                "session_store", FileSessionStore(state_root / "sessions")
            )
            kwargs.setdefault(
                "memory_store", FileMemoryStore(state_root / "memory.json")
            )
            kwargs.setdefault("code_mode", True)
            kwargs.setdefault(
                "context_window_tokens",
                get_model_limits(getattr(llm, "model", None)).context_window,
            )
            kwargs.setdefault("max_tool_output_chars", 16_000)
            kwargs.setdefault("max_iterations", 12)
            kwargs.setdefault("parallel_tool_execution", True)
            kwargs.setdefault("max_tool_concurrency", 4)
        return cls.with_builtins(
            llm=llm,
            project_root=project_root,
            **kwargs,
        )
