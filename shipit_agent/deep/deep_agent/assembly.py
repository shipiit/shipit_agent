"""How a DeepAgent assembles its inner Agent: tools, memory and constructor arguments."""

from __future__ import annotations

from typing import Any

from shipit_agent.agent_setup.builtins import get_builtin_tools

from .delegation import build_delegation_tool
from .toolset import deep_tool_set, merge_tools


class _DeepAgentAssembly:
    """How a DeepAgent assembles its inner Agent: tools, memory and constructor arguments."""

    def _builtin_tools(self) -> list[Any]:
        if not self.use_builtins:
            return []
        return get_builtin_tools(
            llm=self.llm,
            project_root=str(self.project_root),
            workspace_root=self.workspace_root,
            web_search_provider=self.web_search_provider,
            web_search_api_key=self.web_search_api_key,
            web_search_config=self.web_search_config,
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
            "decision_llm": self.decision_llm,
            "progress_summaries": self.progress_summaries,
            "prompt": self.prompt,
            "tools": tools,
            "mcps": list(self.mcps),
            "name": self.name,
            "description": self.description,
            "metadata": dict(self.metadata),
            "rag": self.rag,
            "memory_store": memory_store,
            "session_store": self.session_store,
            "session_id": self.session_id,
            "max_iterations": self.max_iterations,
            "parallel_tool_execution": self.parallel_tool_execution,
            "max_tool_concurrency": self.max_tool_concurrency,
            "context_window_tokens": self.context_window_tokens,
            "max_tool_output_chars": self.max_tool_output_chars,
            "replan_interval": self.replan_interval,
            "skill_registry": self.skill_registry,
            "skill_source": self.skill_source,
            "auto_use_skills": self.auto_use_skills,
            "auto_project_skills": self.auto_project_skills,
            "skills": list(self.skills),
            "default_skill_ids": list(self.default_skill_ids),
            "skill_match_limit": self.skill_match_limit,
            "project_root": self.project_root,
            "verifier": self.verifier,
            "permission_mode": self.permission_mode,
            "permissions": self.permissions,
            "permission_callback": self.permission_callback,
            "guardrails": self.guardrails,
            "approvals": self.approvals,
            "code_mode": self.code_mode,
            "lockdown": self.lockdown,
            "heal_tool_calls": self.heal_tool_calls,
        }
        combined_history = [*list(self.history), *history]
        if combined_history:
            kwargs["history"] = combined_history
        for name, value in (
            ("retry_policy", self.retry_policy),
            ("router_policy", self.router_policy),
            ("hooks", self.hooks),
            ("trace_store", self.trace_store),
            ("trace_id", self.trace_id),
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
