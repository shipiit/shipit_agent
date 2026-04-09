# Prebuilt Tools

SHIPIT Agent ships with a rich set of built-in tools. Use `Agent.with_builtins(...)` to load them all, or import individually.

## Core tools

| Tool | Purpose | Key kwargs |
|---|---|---|
| `WebSearchTool` | Search the web via DuckDuckGo, Brave, Serper, Tavily, or Playwright | `provider`, `api_key`, `provider_config` |
| `OpenURLTool` | Fetch a URL via in-process Playwright (primary) or urllib (fallback) | `timeout`, `max_chars`, `user_agent`, `headless` |
| `PlaywrightBrowserTool` | Drive a headless browser for interactive / JS-heavy pages | `headless`, `timeout` |
| `ToolSearchTool` | Rank available tools by relevance to a query | `max_limit`, `default_limit`, `token_bonus` |
| `AskUserTool` | Pause the agent and ask the user a clarifying question | — |
| `HumanReviewTool` | Request human approval before a risky action | — |
| `PlannerTool` | Generate a structured execution plan | — |
| `MemoryTool` | Store and retrieve facts across turns | — |
| `WorkspaceFilesTool` | Read/write/list files in a scratch directory | `root_dir` |
| `CodeExecutionTool` | Execute Python code in a sandboxed subprocess | `workspace_root` |
| `ArtifactBuilderTool` | Generate single-file HTML artifacts (dashboards, charts) | — |
| `SubAgentTool` | Delegate a focused subtask to a lightweight LLM call | `llm` |

## Reasoning helpers

| Tool | Purpose |
|---|---|
| `PromptTool` | Apply a prompt template to some data (summarize, extract, reformat) |
| `VerifierTool` | Check an assertion against gathered evidence |
| `ThoughtDecompositionTool` | Break a complex task into subtasks |
| `EvidenceSynthesisTool` | Combine multiple tool outputs into a single reasoned conclusion |
| `DecisionMatrixTool` | Score options across criteria |

## Third-party connectors

These use the `CredentialStore` for OAuth/API-key management:

| Tool | Service |
|---|---|
| `GmailTool` | Gmail (read, send, search) |
| `GoogleDriveTool` | Google Drive (list, read, upload) |
| `GoogleCalendarTool` | Google Calendar (list, create, update) |
| `SlackTool` | Slack (post messages, read channels) |
| `LinearTool` | Linear (issues, projects) |
| `JiraTool` | Jira (issues, comments) |
| `NotionTool` | Notion (pages, databases) |
| `ConfluenceTool` | Confluence (pages, spaces) |
| `CustomAPITool` | Any REST API with custom auth |

## Loading them

```python
from shipit_agent import Agent

# All built-ins:
agent = Agent.with_builtins(llm=llm)

# Selective:
from shipit_agent import Agent, WebSearchTool, OpenURLTool, ToolSearchTool

agent = Agent(
    llm=llm,
    tools=[
        WebSearchTool(),
        OpenURLTool(),
        ToolSearchTool(),
    ],
)
```

## Related

- [Tool search](tool-search.md) — semantic discovery across many tools
- [Custom tools](custom-tools.md) — build your own
