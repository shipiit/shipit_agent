# Tools Manifest

Complete list of built-in tools with file paths.

## Core tools

| Tool class | Module path |
|---|---|
| `WebSearchTool` | `shipit_agent.tools.web_search.web_search_tool` |
| `OpenURLTool` | `shipit_agent.tools.open_url.open_url_tool` |
| `PlaywrightBrowserTool` | `shipit_agent.tools.playwright_browser.playwright_browser_tool` |
| `BashTool` | `shipit_agent.tools.bash.bash_tool` |
| `FileReadTool` | `shipit_agent.tools.file_read.file_read_tool` |
| `EditFileTool` | `shipit_agent.tools.edit_file.edit_file_tool` |
| `FileWriteTool` | `shipit_agent.tools.file_write.file_write_tool` |
| `GlobSearchTool` | `shipit_agent.tools.glob_search.glob_search_tool` |
| `GrepSearchTool` | `shipit_agent.tools.grep_search.grep_search_tool` |
| `ToolSearchTool` | `shipit_agent.tools.tool_search.tool_search_tool` |
| `AskUserTool` | `shipit_agent.tools.ask_user.ask_user_tool` |
| `HumanReviewTool` | `shipit_agent.tools.human_review.human_review_tool` |
| `PlannerTool` | `shipit_agent.tools.planner.planner_tool` |
| `MemoryTool` | `shipit_agent.tools.memory.memory_tool` |
| `WorkspaceFilesTool` | `shipit_agent.tools.workspace_files.workspace_files_tool` |
| `CodeExecutionTool` | `shipit_agent.tools.code_execution.code_execution_tool` |
| `ArtifactBuilderTool` | `shipit_agent.tools.artifact_builder.artifact_builder_tool` |
| `SubAgentTool` | `shipit_agent.tools.sub_agent.sub_agent_tool` |

## Reasoning helpers

| Tool class | Module path |
|---|---|
| `PromptTool` | `shipit_agent.tools.prompt.prompt_tool` |
| `VerifierTool` | `shipit_agent.tools.verifier.verifier_tool` |
| `ThoughtDecompositionTool` | `shipit_agent.tools.thought_decomposition` |
| `EvidenceSynthesisTool` | `shipit_agent.tools.evidence_synthesis` |
| `DecisionMatrixTool` | `shipit_agent.tools.decision_matrix` |

## Third-party connectors

| Tool class | Service |
|---|---|
| `GmailTool` | Gmail |
| `GoogleCalendarTool` | Google Calendar |
| `GoogleDriveTool` | Google Drive |
| `SlackTool` | Slack |
| `LinearTool` | Linear |
| `JiraTool` | Jira |
| `NotionTool` | Notion |
| `ConfluenceTool` | Confluence |
| `CustomAPITool` | Arbitrary REST API |

All connectors use `shipit_agent.integrations.CredentialStore` for auth.

## Related

- [Prebuilt tools guide](../guides/prebuilt-tools.md)
- [Custom tools guide](../guides/custom-tools.md)
