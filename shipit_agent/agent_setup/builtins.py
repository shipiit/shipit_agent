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
    Apps:               create_app, use_app, set_app_binding, list_blueprints
    Interaction:        ask_user, ask_user_async, human_review, give_up,
                        connections
    Planning:           plan_task, decompose_problem, todo
    Reasoning:          synthesize_evidence, decision_matrix, verify_output
    Building:           build_artifact, build_prompt, render_dashboard
    Content:            pdf, vision
    Data:               sql
    Memory & search:    memory, tool_search
    Sub-agents:         sub_agent (requires llm)
    Connectors:         gmail, google_calendar, google_drive, google_sheets,
                        slack, linear, jira, notion, confluence, github,
                        gitlab, figma, salesforce, stripe, zendesk,
                        linkedin_search, custom_api

Note: ``SubAgentTool`` requires an ``llm`` and is only included when
``llm`` is passed. All other tools are stateless or self-contained.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLM
from shipit_agent.tools.connections import ConnectionsTool
from shipit_agent.tools.describe_binding import DescribeBindingTool
from pathlib import Path

from shipit_agent.tools.apps import app_tools
from shipit_agent.tools.give_up import GiveUpTool
from shipit_agent.tools import (
    AskUserAsyncTool,
    AskUserTool,
    ArtifactBuilderTool,
    DeepResearchTool,
    DocumentBuilderTool,
    DownloadFileTool,
    BashTool,
    BashJobTool,
    CodeExecutionTool,
    ConfluenceTool,
    CustomAPITool,
    DashboardRenderTool,
    DecisionMatrixTool,
    EditFileTool,
    MultiEditTool,
    EvidenceSynthesisTool,
    FigmaTool,
    FileReadTool,
    FileWriteTool,
    GitHubTool,
    GitOpsTool,
    GitLabTool,
    GmailTool,
    GlobSearchTool,
    GoogleCalendarTool,
    GoogleDriveTool,
    GoogleSheetsTool,
    GrepSearchTool,
    HumanReviewTool,
    JiraTool,
    LinearTool,
    LinkedInSearchTool,
    MemoryTool,
    NotebookEditTool,
    NotionTool,
    OpenURLTool,
    PDFTool,
    PlannerTool,
    PresentFileTool,
    PresentPlanTool,
    PlaywrightBrowserTool,
    PromptTool,
    SalesforceTool,
    SQLTool,
    StripeTool,
    SubAgentTool,
    TextToSpeechTool,
    TodoTool,
    VideoGenerateTool,
    Tool,
    ImageGenerateTool,
    ToolSearchTool,
    VerifierTool,
    VisionTool,
    WebSearchTool,
    WorkspaceFilesTool,
    SlackTool,
    ThoughtDecompositionTool,
    ZendeskTool,
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
    # Built once so the companion bash_job tool shares its live job table.
    bash_tool = BashTool(root_dir=project_root)
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
        bash_tool,
        BashJobTool(bash_tool),
        FileReadTool(root_dir=project_root),
        EditFileTool(root_dir=project_root),
        MultiEditTool(root_dir=project_root),
        FileWriteTool(root_dir=project_root),
        GlobSearchTool(root_dir=project_root),
        GrepSearchTool(root_dir=project_root),
        NotebookEditTool(root_dir=project_root),
        GitOpsTool(root_dir=project_root),
        # ── apps ──────────────────────────────────────────────────
        # Something the agent builds once and runs again: create_app,
        # set_app_binding, use_app, list_blueprints. They live under the
        # project so an app outlives the run that wrote it.
        *app_tools(
            str(Path(project_root) / ".shipit" / "apps"),
            workdir=project_root,
        ),
        # ── interaction ───────────────────────────────────────────
        AskUserTool(),
        AskUserAsyncTool(),
        HumanReviewTool(),
        # Declaring "I'm blocked" is an interaction, not a failure mode.
        GiveUpTool(),
        # ── planning & reasoning ──────────────────────────────────
        MemoryTool(),
        PlannerTool(),
        PresentPlanTool(),
        TodoTool(),
        ThoughtDecompositionTool(),
        EvidenceSynthesisTool(),
        DecisionMatrixTool(),
        PromptTool(),
        VerifierTool(),
        ToolSearchTool(),
        # Progressive discovery: learn one binding's API instead of carrying
        # every integration's schema in the prompt (see shipit_agent.codemode).
        DescribeBindingTool(),
        # What is connected, and what the agent needs you to connect.
        ConnectionsTool(),
        # ── building ──────────────────────────────────────────────
        ArtifactBuilderTool(),
        DocumentBuilderTool(workspace_root=f"{workspace_root}/documents"),
        DownloadFileTool(workspace_root=f"{workspace_root}/downloads"),
        DeepResearchTool(),
        WorkspaceFilesTool(root_dir=workspace_root),
        CodeExecutionTool(workspace_root=f"{workspace_root}/code_execution"),
        DashboardRenderTool(workspace_root=f"{workspace_root}/dashboards"),
        # ── content extraction ────────────────────────────────────
        PDFTool(),
        VisionTool(llm=llm),
        # ── deliverables ──────────────────────────────────────────
        PresentFileTool(root_dir=workspace_root),
        # ── media generation (gated: hidden unless a backend is available) ──
        ImageGenerateTool(output_dir=f"{workspace_root}/images"),
        TextToSpeechTool(output_dir=f"{workspace_root}/audio"),
        VideoGenerateTool(output_dir=f"{workspace_root}/videos"),
        # ── data & databases ──────────────────────────────────────
        SQLTool(),
        # ── connectors (SaaS integrations) ────────────────────────
        GmailTool(),
        GoogleCalendarTool(),
        GoogleDriveTool(),
        GoogleSheetsTool(),
        SlackTool(),
        LinearTool(),
        JiraTool(),
        NotionTool(),
        ConfluenceTool(),
        GitHubTool(),
        GitLabTool(),
        FigmaTool(),
        SalesforceTool(),
        StripeTool(),
        ZendeskTool(),
        LinkedInSearchTool(),
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
