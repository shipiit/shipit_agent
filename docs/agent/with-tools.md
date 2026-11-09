---
title: Tools
description: The built-in tools, how to choose which an agent gets, and how to add your own, MCP servers and other agents.
---

# Tools

A tool is something the model can do: read a file, run a command, search the web, post to Slack. shipit has 66 built in, and you can add your own as functions, classes, MCP servers or other agents.

## The built-in tools

`Agent.with_builtins()` gives an agent all of them. Tools whose service is not configured (no token, no package) stay hidden from the model.

| Group | Tools |
| :- | :- |
| **Files and code** | `read_file`, `write_file`, `edit_file`, `multi_edit`, `notebook_edit`, `glob_files`, `grep_files`, `bash`, `bash_job`, `run_code`, `git_ops`, `workspace_files`, `download_file`, `present_file`, `pdf` |
| **The web** | `web_search`, `open_url`, `playwright_browse`, `deep_research` |
| **Planning and checking** | `todo`, `plan_task`, `present_plan`, `decompose_problem`, `decision_matrix`, `synthesize_evidence`, `verify_output`, `build_prompt`, `give_up` |
| **People** | `ask_user`, `ask_user_async`, `human_review` |
| **Agents and tools** | `sub_agent`, `task_stop`, `tool_search` |
| **Memory** | `memory` |
| **Media** | `vision`, `image_generate`, `text_to_speech`, `video_generate` |
| **Documents and apps** | `build_artifact`, `build_document`, `render_dashboard`, `create_app`, `use_app`, `list_blueprints`, `set_app_binding`, `describe_binding` |
| **Services** | `github`, `gitlab`, `jira`, `linear`, `notion`, `confluence`, `slack`, `gmail_search`, `google_calendar`, `google_drive`, `google_sheets`, `figma`, `salesforce`, `stripe`, `zendesk`, `linkedin_search`, `sql`, `custom_api`, `connections` |

The [Tools catalog](../tools/index.md) documents each one. The file tools share some rules:

- They work inside `project_root` and any `add_dirs`, and refuse paths outside.
- `edit_file` needs the file to have been read first, and refuses if it changed on disk since.
- Long output is clipped to its start and end, and the full text is saved to a file the model can read.

## Choosing the tools

Give an agent only what it needs: fewer tools mean smaller requests and fewer wrong choices.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools import BashTool, EditFileTool, FileReadTool, GrepSearchTool

agent = Agent(
    llm=build_llm_from_env(),
    project_root=".",
    tools=[FileReadTool(root_dir="."), GrepSearchTool(root_dir="."), EditFileTool(root_dir="."), BashTool(root_dir=".")],
)
```
With the SDK API, name them: `AgentOptions(tools=["read_file", "grep_files", "edit_file", "bash"])`. Leaving `tools` out gives the core set: files, bash, search, the web, todos, questions and memory.

To keep every built-in except a few, use `disallowed_tools=["bash", "playwright_browse"]`.

## Your own tools

Any function becomes a tool; its docstring and type hints become the schema.

```python
from shipit_agent.tools import FunctionTool


def exchange_rate(base: str, quote: str) -> str:
    """The current exchange rate from one currency to another, e.g. USD to EUR."""
    return f"1 {base} = 0.92 {quote}"


rate_tool = FunctionTool.from_callable(exchange_rate, read_only=True)
```
Pass it in `tools=[rate_tool]`. For full control (a hand-written schema, rich output, errors the model can act on), write a tool class. [Custom tools](../guides/custom-tools.md).

## MCP servers

An MCP server's tools join the agent's own. Connect one from the catalog, or point at any server:

```python
import os

from shipit_agent import Agent, MCPStdioTransport, RemoteMCPServer, connect_mcp
from shipit_agent.llms import build_llm_from_env

github = connect_mcp("github", token=os.environ["GITHUB_TOKEN"])
files = RemoteMCPServer(
    name="files",
    transport=MCPStdioTransport(command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]),
)
agent = Agent.with_builtins(llm=build_llm_from_env(), mcps=[github, files])
```
[MCP servers](../guides/mcp.md) covers HTTP and SSE servers, filtering their tools and in-process servers.

## Other agents as tools

An agent can call another as a tool: a reviewer, a researcher, a specialist with its own prompt and model.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

llm = build_llm_from_env()
reviewer = Agent.with_builtins(llm=llm, name="reviewer", prompt="Review code for bugs. Be specific.")
lead = Agent.with_builtins(llm=llm, tools=[reviewer.as_tool(description="Reviews a diff for bugs.")])
```
[Agents as tools](../guides/agents-as-tools.md) and [Sub-agents](../guides/delegation.md).

## Many tools, small requests

Tool schemas are sent with every request. With dozens of tools, that is thousands of tokens per turn. `deferred_tools=True` keeps a small core loaded and lists the rest by name; the model loads one with `tool_search` when it needs it.

```python
agent = Agent.with_builtins(llm=llm, deferred_tools=True)
```
[Tool search](../guides/tool-search.md).
