---
title: Tool Catalog
description: Complete reference for every built-in tool in shipit-agent — what each one does, when to use it, schema, examples, and configuration knobs.
---

# Tool Catalog

shipit-agent ships with **25+ production-ready built-in tools** organized into four categories. Every tool is opt-in (use only what you need), discoverable via [`tool_search`](../guides/tool-search.md), and follows the same `Tool` protocol so you can mix built-ins with custom tools without ceremony.

## Quick navigation

<div class="grid cards" markdown>

-   :material-toolbox: **[Core tools](core-tools.md)**

    ---

    The runtime essentials. Web search, URL fetching, browser automation, semantic tool discovery, human-in-the-loop, planning.

    `web_search` · `open_url` · `playwright_browse` · `tool_search` · `ask_user` · `human_review` · `plan_task`

-   :material-brain: **[Reasoning helpers](reasoning-helpers.md)**

    ---

    Tools that decompose, verify, and synthesize. Build prompts, check outputs, break problems apart, weigh options.

    `build_prompt` · `verify_output` · `decompose_problem` · `synthesize_evidence` · `decision_matrix` · `sub_agent`

-   :material-code-braces: **[Code & files](code-and-files.md)**

    ---

    Execute Python, manage workspace files, store memory facts, build artifacts.

    `bash` · `read_file` · `edit_file` · `write_file` · `glob_files` · `grep_files` · `run_code` · `workspace_files` · `memory` · `build_artifact`

-   :material-script-text: **Tool prompt pages**

    ---

    Exact shipped prompt text and runtime notes for the main code-and-files tools.

    `bash` · `read_file` · `edit_file` · `write_file` · `glob_files` · `grep_files`

-   :material-link-variant: **[Connectors](connectors.md)**

    ---

    Third-party SaaS integrations with OAuth/API-key auth via `CredentialStore`.

    `gmail_search` · `google_drive` · `google_calendar` · `slack` · `linear` · `jira` · `notion` · `confluence` · `custom_api`

</div>

## Full alphabetical index

| Tool | Category | Purpose |
|---|---|---|
| [`build_artifact`](code-and-files.md#build_artifact) | Code & files | Create named artifacts (markdown, JSON, code files) saved to workspace |
| [`ask_user`](core-tools.md#ask_user) | Core | Pause and ask the user a structured question |
| [`bash`](bash.md) | Code & files | Run a bounded shell command from the configured project root |
| [`build_prompt`](reasoning-helpers.md#build_prompt) | Reasoning | Generate or refine a system prompt from goals + constraints |
| [`run_code`](code-and-files.md#run_code) | Code & files | Run Python or shell code in a sandboxed subprocess |
| [`confluence`](connectors.md#confluence) | Connector | Search and create Confluence pages |
| [`custom_api`](connectors.md#custom_api) | Connector | Call any configured HTTP API with custom auth |
| [`decision_matrix`](reasoning-helpers.md#decision_matrix) | Reasoning | Score options against criteria, recommend the strongest |
| [`decompose_problem`](reasoning-helpers.md#decompose_problem) | Reasoning | Break a problem into workstreams, assumptions, risks |
| [`edit_file`](edit-file.md) | Code & files | Apply exact string replacement patches to an existing file |
| [`gmail_search`](connectors.md#gmail_search) | Connector | Search, read, draft, and send Gmail messages |
| [`google_calendar`](connectors.md#google_calendar) | Connector | Search and list calendar events |
| [`google_drive`](connectors.md#google_drive) | Connector | Search and list Drive files |
| [`human_review`](core-tools.md#human_review) | Core | Pause for human approval before continuing |
| [`jira`](connectors.md#jira) | Connector | Search and create Jira issues |
| [`linear`](connectors.md#linear) | Connector | Search and create Linear issues |
| [`memory`](code-and-files.md#memory) | Code & files | Store and retrieve persistent memory facts |
| [`notion`](connectors.md#notion) | Connector | Search and create Notion pages |
| [`open_url`](core-tools.md#open_url) | Core | Fetch a URL with in-process Playwright + urllib fallback |
| [`plan_task`](core-tools.md#plan_task) | Core | Generate a structured execution plan |
| [`playwright_browse`](core-tools.md#playwright_browse) | Core | Drive a headless browser for JS-heavy or interactive pages |
| [`slack`](connectors.md#slack) | Connector | Search and post Slack messages |
| [`sub_agent`](reasoning-helpers.md#sub_agent) | Reasoning | Delegate a focused subtask to a lightweight LLM call |
| [`synthesize_evidence`](reasoning-helpers.md#synthesize_evidence) | Reasoning | Turn observations into facts, inferences, gaps, recommendations |
| [`tool_search`](core-tools.md#tool_search) | Core | Rank available tools by relevance to a query |
| [`verify_output`](reasoning-helpers.md#verify_output) | Reasoning | Check whether content satisfies required criteria |
| [`web_search`](core-tools.md#web_search) | Core | Search the web via DuckDuckGo, Brave, Serper, Tavily, or Playwright |
| [`workspace_files`](code-and-files.md#workspace_files) | Code & files | Read, write, list, and inspect files in the workspace |
| [`read_file`](read-file.md) | Code & files | Read a file from the configured project root |
| [`write_file`](write-file.md) | Code & files | Create or overwrite a file under the configured project root |
| [`glob_files`](glob-files.md) | Code & files | Find files by glob pattern under the configured project root |
| [`grep_files`](grep-files.md) | Code & files | Search repository contents with ripgrep-style semantics |

## How tools are loaded

Three ways, pick whichever fits:

**Way 1 — Everything at once:**

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(llm=OpenAIChatLLM(model="gpt-4o-mini"))
# All 25+ built-in tools registered automatically
```

**Way 2 — Selective:**

```python
from shipit_agent import Agent, WebSearchTool, OpenURLTool, ToolSearchTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[
        WebSearchTool(),
        OpenURLTool(),
        ToolSearchTool(),
    ],
)
```

**Way 3 — Mix built-ins with custom tools:**

```python
from shipit_agent import Agent, FunctionTool, get_builtin_tools
from shipit_agent.llms import OpenAIChatLLM

def my_pricing_lookup(sku: str) -> str:
    """Look up internal product pricing by SKU."""
    return get_pricing_from_db(sku)

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    tools=[
        *get_builtin_tools(llm=OpenAIChatLLM(model="gpt-4o-mini")),
        FunctionTool.from_callable(my_pricing_lookup),
    ],
)
```

## How tools surface in events

Every tool call emits three events the runtime guarantees in this order:

```
tool_called      → "Tool called: web_search"           (before execution)
tool_completed   → "Tool completed: web_search"        (on success)
tool_failed      → "Tool failed: web_search"           (on error or unknown tool)
```

Both `tool_called` and `tool_completed` carry the full arguments and output in their event payloads. See the [Event types reference](../reference/events.md) for the complete schema.

## Bedrock tool-pairing safety

The runtime guarantees that **every `toolUse` block in an assistant turn gets a paired `toolResult` block** in the next user turn — even when:

- A tool raises a non-retryable exception → synthetic error result is appended
- The model hallucinates an unregistered tool name → synthetic "Error: tool X is not registered" result
- The planner runs before the first LLM call → output is injected as a `user`-role context message, not an orphan `tool`-role result

This invariant is what makes multi-iteration tool loops on AWS Bedrock work reliably. See [architecture](../reference/architecture.md#1-tool-useresult-pairing) for the full story.

## Adding your own tool

Every tool implements three things: `name`, `schema()`, and `run(context, **kwargs)`. See the [custom tools guide](../guides/custom-tools.md) for the full template, or the worked example in [`examples/05_custom_tool.py`](https://github.com/shipiit/shipit_agent/blob/main/examples/05_custom_tool.py).

## Where these are defined

Every built-in tool lives at `shipit_agent/tools/<tool_name>/<tool_name>_tool.py`. The implementation is small, readable, and a good template for your own tools — the Web search tool is ~150 lines including all five provider backends.

## Related

- [Custom tools guide](../guides/custom-tools.md) — build a new tool from scratch
- [Tool search](../guides/tool-search.md) — semantic discovery across many tools
- [Architecture](../reference/architecture.md) — how tools fit into the runtime loop
- [Event types](../reference/events.md) — `tool_called` / `tool_completed` / `tool_failed` payloads
