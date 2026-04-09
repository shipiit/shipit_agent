# SHIPIT Agent Tool Guide

This document is the dedicated tool reference for `shipit_agent`.

Use it when you want to:

- understand what each built-in tool does
- decide which tool belongs in a workspace agent
- create your own local project tools
- attach connector tools cleanly
- design tools that are reliable in real product chat flows

## Tool Model

Every tool in `shipit_agent` follows the same basic contract:

| Field Or Method | Meaning |
| --- | --- |
| `name` | Unique tool name exposed to the model. |
| `description` | Short capability summary shown to the model. |
| `prompt` | Default tool-specific prompt guidance. |
| `prompt_instructions` | Extra instructions merged into the runtime tool prompt block. |
| `schema()` | JSON schema used for model tool calling. |
| `run(context, **kwargs)` | Execution entrypoint that returns `ToolOutput`. |

Runtime data passed into tools:

| Context Field | Meaning |
| --- | --- |
| `prompt` | Current user prompt for this run. |
| `system_prompt` | Resolved runtime system prompt. |
| `metadata` | Agent metadata dictionary. |
| `state` | Shared runtime state for stores, credentials, and workspace info. |
| `session_id` | Session identifier for chat-style persistence. |

## Tool Families

`shipit_agent` tools fall into practical groups:

| Group | Purpose | Tools |
| --- | --- | --- |
| Research and browsing | Find and inspect external information. | `WebSearchTool`, `OpenURLTool`, `PlaywrightBrowserTool` |
| Human in the loop | Ask for clarification or approval. | `AskUserTool`, `HumanReviewTool` |
| Planning and verification | Plan work and check quality. | `PlannerTool`, `PromptTool`, `VerifierTool`, `ToolSearchTool` |
| Structured reasoning | Create visible analysis artifacts for hard tasks. | `ThoughtDecompositionTool`, `EvidenceSynthesisTool`, `DecisionMatrixTool` |
| Workspace execution | Read files, run code, and build outputs. | `MemoryTool`, `ArtifactBuilderTool`, `WorkspaceFilesTool`, `CodeExecutionTool` |
| Connectors | Reach third-party systems and internal APIs. | `GmailTool`, `GoogleCalendarTool`, `GoogleDriveTool`, `SlackTool`, `LinearTool`, `JiraTool`, `NotionTool`, `ConfluenceTool`, `CustomAPITool` |
| Delegation | Hand off bounded work to another agent. | `SubAgentTool` |

## Built-In Tools

### Research And Browsing

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `WebSearchTool` | Provider-backed web search. | `provider`, `api_key`, `provider_config`, `name`, `description`, `prompt` | Supports `playwright`, `duckduckgo`, `brave`, `serper`, and `tavily`. |
| `OpenURLTool` | Fetch and extract content from a URL. | `timeout`, `max_chars`, `user_agent`, `name`, `description`, `prompt` | Good after search when the model needs direct page content. |
| `PlaywrightBrowserTool` | Inspect rendered pages. | `name`, `description`, `prompt` | Better than raw fetch for interactive or JS-heavy pages. |

### Human In The Loop

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `AskUserTool` | Ask the user for clarification. | `name`, `description`, `prompt` | Emits interactive events in the runtime. |
| `HumanReviewTool` | Request explicit review or approval. | `name`, `description`, `prompt` | Useful before sending, changing, or publishing something. |

### Planning And Quality

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `PlannerTool` | Create a plan and checkpoints. | `name`, `description`, `prompt` | Can be invoked automatically through `RouterPolicy`. |
| `PromptTool` | Build strong prompts for another step or agent. | `name`, `description`, `prompt` | Useful for reusable prompt generation. |
| `VerifierTool` | Check whether output meets a standard. | `name`, `description`, `prompt` | Good for self-check and pre-delivery review. |
| `ToolSearchTool` | Search the available tool catalog. | `name`, `description`, `prompt` | Helps the model discover the right tool in a large registry. |

### Structured Reasoning

These are safe “thinking tools.” They do not expose private chain-of-thought. Instead, they create visible reasoning artifacts the user can inspect.

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `ThoughtDecompositionTool` | Break a hard problem into workstreams, assumptions, risks, evidence needs, and next actions. | `name`, `description`, `prompt` | Good at the start of multi-stage tasks. |
| `EvidenceSynthesisTool` | Distill observations into facts, inferences, gaps, and recommendations. | `name`, `description`, `prompt` | Good after search, workspace reads, or connector actions. |
| `DecisionMatrixTool` | Compare options against explicit criteria and recommend one clearly. | `name`, `description`, `prompt` | Good when the agent must choose a path transparently. |

### Workspace Execution

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `MemoryTool` | Read and write memory facts. | `name`, `description`, `prompt` | Uses the configured memory store. |
| `ArtifactBuilderTool` | Build structured artifacts and export files. | `workspace_root`, `name`, `description`, `prompt` | Good for reports, summaries, and saved outputs. |
| `WorkspaceFilesTool` | Inspect local files in a workspace. | `root_dir`, `name`, `description`, `prompt` | Keep one workspace root per project or tenant. |
| `CodeExecutionTool` | Run local code inside supported interpreters. | `workspace_root`, `name`, `description`, `prompt` | Supports Python, shell, JS, TS, Ruby, PHP, Perl, Lua, and R if installed. |

### Connectors

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `GmailTool` | Search, read, draft, send, and inspect Gmail. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Supports `search`, `read_message`, `read_thread`, `get_attachment`, `list_labels`, `create_draft`, `send_message`. |
| `GoogleCalendarTool` | Calendar lookup workflows. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Use for event discovery and calendar context. |
| `GoogleDriveTool` | Google Drive file search. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Useful for workspace file discovery. |
| `SlackTool` | Slack messaging and discovery. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Supports channel history, replies, posting, search, and user lookup. |
| `LinearTool` | Linear issue and project workflows. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Supports issue search, create, update, get, team listing, and project listing. |
| `JiraTool` | Jira ticket workflows. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Supports transitions, comments, assignment, creation, search, and lookup. |
| `NotionTool` | Notion page workflows. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Good for knowledge base search and content creation. |
| `ConfluenceTool` | Confluence page workflows. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Good for documentation and wiki search. |
| `CustomAPITool` | Reach unsupported HTTP APIs. | `credential_key`, `credential_store`, `name`, `description`, `prompt` | Best for internal services and one-off integrations. |

### Delegation

| Tool | Purpose | Main Fields | Notes |
| --- | --- | --- | --- |
| `SubAgentTool` | Delegate bounded work to another agent. | `llm`, `name`, `description`, `prompt` | Useful when one sub-task should be isolated from the main run. |

## How To Create A New Tool

There are two primary paths.

### 1. Wrap A Python Callable

Use this when the tool is simple and local.

```python
from shipit_agent import FunctionTool


def project_summary() -> str:
    return "Return local project context for this workspace."


tool = FunctionTool.from_callable(
    project_summary,
    name="project_summary",
    description="Return project context for the current workspace.",
)
```

Use this pattern for:

- pure Python utilities
- deterministic local helpers
- small business-logic helpers
- project-specific formatting or summarization

Template file:

- `examples/custom_function_tool_template.py`

### 2. Build A Full Tool Class

Use this when the tool needs configuration, state, or multiple parameters.

```python
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


class RepoInfoTool:
    name = "repo_info"
    description = "Return repository-specific metadata."
    prompt = "Use this when local repository metadata is needed."
    prompt_instructions = "Prefer this over guessing repository conventions."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Requested metadata area",
                        }
                    },
                    "required": ["topic"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        topic = str(kwargs.get("topic", "")).strip()
        return ToolOutput(text=f"Metadata for: {topic}")
```

Use this pattern for:

- tools with multiple actions
- tools with credentials
- tools that read workspace or runtime state
- tools with richer structured metadata

Template files:

- `examples/custom_workspace_tool_template.py`
- `examples/reasoning_agent_template.py`

## Tool Design Rules

If you want users to attach tools in any workspace cleanly, follow these rules:

| Rule | Why It Matters |
| --- | --- |
| Keep tool names unique and stable. | Prevents model confusion and registry collisions. |
| Write a short concrete `description`. | Tool selection quality depends on it. |
| Add a strong `prompt` and `prompt_instructions`. | This is often the difference between a useful tool and a ignored one. |
| Keep schemas explicit. | Ambiguous schemas produce weak tool calls. |
| Return useful `metadata`. | Makes downstream inspection and tracing stronger. |
| Use `credential_store` instead of hardcoding secrets. | Makes tools reusable across workspaces and deployments. |
| Scope file access to a workspace root. | Prevents accidental cross-project behavior. |
| Fail with clear messages. | The model and the user both need actionable failure output. |
| Prefer one tool per domain responsibility. | Keeps tool choice cleaner and simpler. |

## How To Attach Tools To An Agent

### Local Tool Example

```python
from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import SimpleEchoLLM


def add_numbers(a: int, b: int) -> str:
    return str(a + b)


agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[
        FunctionTool.from_callable(
            add_numbers,
            name="add_numbers",
            description="Add two integers and return the result.",
        )
    ],
)
```

### Built-Ins Plus Custom Tools

```python
from shipit_agent import Agent, FunctionTool, get_builtin_tools
from shipit_agent.llms import BedrockChatLLM


def project_context() -> str:
    return "This is the billing workspace."


llm = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
tools = get_builtin_tools(llm=llm, workspace_root=".shipit_workspace")
tools.append(FunctionTool.from_callable(project_context, name="project_context"))

agent = Agent(llm=llm, tools=tools)
```

### Workspace-Oriented Pattern

For multi-project or multi-tenant use:

- keep one `workspace_root` per project
- keep one `session_id` per conversation
- keep one `credential_store` per deployment or tenant boundary
- add only the tools that the workspace actually needs

## Connector Tool Pattern

Connector tools should use the credential store instead of inline secrets.

```python
from shipit_agent import Agent, CredentialRecord, FileCredentialStore, SlackTool
from shipit_agent.llms import SimpleEchoLLM

credential_store = FileCredentialStore(".shipit_workspace/credentials.json")
credential_store.set(
    CredentialRecord(
        key="slack",
        provider="slack",
        secrets={"token": "SLACK_BOT_TOKEN"},
    )
)

agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[SlackTool(credential_store=credential_store)],
    credential_store=credential_store,
)
```

This keeps tools portable across:

- local development
- notebooks
- scripts
- chat apps
- production services

## Prompt Files For Tools

`shipit_agent` keeps per-tool prompt files in each tool directory, for example:

- `shipit_agent/tools/web_search/prompt.py`
- `shipit_agent/tools/slack/prompt.py`
- `shipit_agent/tools/gmail/prompt.py`

This pattern matters because:

- each tool owns its own usage guidance
- prompts stay close to implementation
- adding a new tool does not require editing one giant prompt file

When you create a new tool directory, add a `prompt.py` with a default prompt constant and use it inside the tool class.

## Recommended Powerful Agent Setups

### Project Chat Agent

- built-ins
- workspace files
- code execution
- planner
- verifier
- session store
- memory store

### Ops Agent

- built-ins
- Gmail
- Slack
- Linear
- Jira
- trace store
- credential store

### Research Agent

- web search
- open URL
- Playwright browser
- MCP docs server
- artifact builder
- verifier

### Reasoning Agent

- built-ins
- `ThoughtDecompositionTool`
- `EvidenceSynthesisTool`
- `DecisionMatrixTool`
- workspace files
- verifier
- session store

## Related Docs

- [README.md](README.md)
- [docs.md](docs.md)
- [notebooks/shipit_agent_test_drive.ipynb](notebooks/shipit_agent_test_drive.ipynb)
- [examples/run_multi_tool_agent.py](examples/run_multi_tool_agent.py)
- [examples/custom_function_tool_template.py](examples/custom_function_tool_template.py)
- [examples/custom_workspace_tool_template.py](examples/custom_workspace_tool_template.py)
- [examples/reasoning_agent_template.py](examples/reasoning_agent_template.py)
