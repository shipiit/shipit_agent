"""Built-in tool catalogue — all 30+ tools that ship with SHIPIT Agent.

This module provides two functions:

- ``get_builtin_tool_map()`` → ``dict[str, Tool]``  (keyed by tool name)
- ``get_builtin_tools()`` → ``list[Tool]``

These are used by:
- ``Agent.with_builtins()`` — to create an agent with all tools pre-wired
- ``DeepAgent.with_builtins()`` — same, plus deep-agent extras
- ``_effective_tools()`` — to resolve skill-linked tools at runtime

Tool categories:

    Web & browsing:     web_search, open_url, playwright_browse
    File operations:    read_file, edit_file, write_file, glob_files, grep_files
    Shell & code:       bash, run_code
    Workspace:          workspace_files
    Interaction:        ask_user, human_review
    Planning:           plan_task, decompose_problem
    Reasoning:          synthesize_evidence, decision_matrix, verify_output
    Building:           build_artifact, build_prompt
    Memory & search:    memory, tool_search
    Sub-agents:         sub_agent (requires llm)
    Connectors:         gmail_search, google_calendar, google_drive,
                        slack, linear, jira, notion, confluence, custom_api

Note: ``SubAgentTool`` requires an ``llm`` and is only included when
``llm`` is passed. All other tools are stateless or self-contained.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLM
from shipit_agent.tools import (
    AskUserTool,
    ArtifactBuilderTool,
    BashTool,
    CodeExecutionTool,
    ConfluenceTool,
    CustomAPITool,
    DecisionMatrixTool,
    EditFileTool,
    EvidenceSynthesisTool,
    FileReadTool,
    FileWriteTool,
    GmailTool,
    GlobSearchTool,
    GoogleCalendarTool,
    GoogleDriveTool,
    GrepSearchTool,
    HumanReviewTool,
    JiraTool,
    LinearTool,
    MemoryTool,
    NotionTool,
    OpenURLTool,
    PlannerTool,
    PlaywrightBrowserTool,
    PromptTool,
    SubAgentTool,
    Tool,
    ToolSearchTool,
    VerifierTool,
    WebSearchTool,
    WorkspaceFilesTool,
    SlackTool,
    ThoughtDecompositionTool,
)


def get_builtin_tool_map(
    *,
    llm: LLM | None = None,
    project_root: str = "/tmp",
    workspace_root: str = ".shipit_workspace",
    web_search_provider: str = "duckduckgo",
    web_search_api_key: str | None = None,
    web_search_config: dict[str, Any] | None = None,
) -> dict[str, Tool]:
    """Create all built-in tools and return them as a ``{name: tool}`` dict.

    The dict keys are the canonical tool names (e.g. ``"read_file"``,
    ``"bash"``, ``"web_search"``). These names are what
    ``SKILL_TOOL_BUNDLES`` references when linking skills to tools.

    Args:
        llm: Model adapter — only needed for ``SubAgentTool``.
        project_root: Base directory for file/shell tools.
        workspace_root: Scoped workspace for ``workspace_files`` and ``run_code``.
        web_search_provider: Search backend (``"duckduckgo"``, ``"tavily"``, etc.).
        web_search_api_key: API key for paid search providers.
        web_search_config: Extra provider-specific config.
    """
    tools: list[Tool] = [
        # ── web & browsing ────────────────────────────────────────
        WebSearchTool(
            provider=web_search_provider,
            api_key=web_search_api_key,
            provider_config=web_search_config,
        ),
        OpenURLTool(),
        PlaywrightBrowserTool(),
        # ── file operations ───────────────────────────────────────
        BashTool(root_dir=project_root),
        FileReadTool(root_dir=project_root),
        EditFileTool(root_dir=project_root),
        FileWriteTool(root_dir=project_root),
        GlobSearchTool(root_dir=project_root),
        GrepSearchTool(root_dir=project_root),
        # ── interaction ───────────────────────────────────────────
        AskUserTool(),
        HumanReviewTool(),
        # ── planning & reasoning ──────────────────────────────────
        MemoryTool(),
        PlannerTool(),
        ThoughtDecompositionTool(),
        EvidenceSynthesisTool(),
        DecisionMatrixTool(),
        PromptTool(),
        VerifierTool(),
        ToolSearchTool(),
        # ── building ──────────────────────────────────────────────
        ArtifactBuilderTool(),
        WorkspaceFilesTool(root_dir=workspace_root),
        CodeExecutionTool(workspace_root=f"{workspace_root}/code_execution"),
        # ── connectors (SaaS integrations) ────────────────────────
        GmailTool(),
        GoogleCalendarTool(),
        GoogleDriveTool(),
        SlackTool(),
        LinearTool(),
        JiraTool(),
        NotionTool(),
        ConfluenceTool(),
        CustomAPITool(),
    ]

    # SubAgentTool requires an LLM to spawn child agents.
    if llm is not None:
        tools.append(SubAgentTool(llm=llm))

    return {tool.name: tool for tool in tools}


def get_builtin_tools(
    *,
    llm: LLM | None = None,
    project_root: str = "/tmp",
    workspace_root: str = ".shipit_workspace",
    web_search_provider: str = "duckduckgo",
    web_search_api_key: str | None = None,
    web_search_config: dict[str, Any] | None = None,
) -> list[Tool]:
    """Convenience wrapper — returns built-in tools as a list."""
    return list(
        get_builtin_tool_map(
            llm=llm,
            project_root=project_root,
            workspace_root=workspace_root,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_config=web_search_config,
        ).values()
    )
