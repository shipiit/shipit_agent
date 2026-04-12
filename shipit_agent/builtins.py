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
    tools: list[Tool] = [
        WebSearchTool(
            provider=web_search_provider,
            api_key=web_search_api_key,
            provider_config=web_search_config,
        ),
        OpenURLTool(),
        PlaywrightBrowserTool(),
        BashTool(root_dir=project_root),
        FileReadTool(root_dir=project_root),
        EditFileTool(root_dir=project_root),
        FileWriteTool(root_dir=project_root),
        GlobSearchTool(root_dir=project_root),
        GrepSearchTool(root_dir=project_root),
        AskUserTool(),
        HumanReviewTool(),
        MemoryTool(),
        PlannerTool(),
        ThoughtDecompositionTool(),
        EvidenceSynthesisTool(),
        DecisionMatrixTool(),
        PromptTool(),
        VerifierTool(),
        ToolSearchTool(),
        ArtifactBuilderTool(),
        WorkspaceFilesTool(root_dir=workspace_root),
        CodeExecutionTool(workspace_root=f"{workspace_root}/code_execution"),
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
