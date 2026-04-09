from __future__ import annotations

from typing import Any

from shipit_agent.llms.base import LLM
from shipit_agent.tools import (
    AskUserTool,
    ArtifactBuilderTool,
    CodeExecutionTool,
    ConfluenceTool,
    CustomAPITool,
    DecisionMatrixTool,
    EvidenceSynthesisTool,
    GmailTool,
    GoogleCalendarTool,
    GoogleDriveTool,
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


def get_builtin_tools(
    *,
    llm: LLM | None = None,
    workspace_root: str = ".shipit_workspace",
    web_search_provider: str = "duckduckgo",
    web_search_api_key: str | None = None,
    web_search_config: dict[str, Any] | None = None,
) -> list[Tool]:
    tools: list[Tool] = [
        WebSearchTool(
            provider=web_search_provider,
            api_key=web_search_api_key,
            provider_config=web_search_config,
        ),
        OpenURLTool(),
        PlaywrightBrowserTool(),
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
    return tools
