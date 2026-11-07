"""Ready-made agents: with the built-in tools, for a project folder, or for a specialist role.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from shipit_agent.agent_setup.builtins import get_builtin_tools
from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT

if TYPE_CHECKING:
    from shipit_agent.agent import Agent


class AgentFactoriesMixin:
    """Ready-made agents: with the built-in tools, for a project folder, or for a specialist role."""

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
            from shipit_agent.context.compaction import get_model_limits

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
        from shipit_agent.agent_setup.builtins import get_builtin_tools
        from shipit_agent.agents.registry import AgentRegistry

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
