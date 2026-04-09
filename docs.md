<p align="center">
  <img src="shipit-icon.svg" alt="SHIPIT" width="120" height="120" />
</p>

<h1 align="center">SHIPIT Agent Docs</h1>

<p align="center">
  <strong>Reference documentation for building powerful tool-using agents with the Shipit runtime.</strong>
</p>

<p align="center">
  <a href="README.md">README</a> ·
  <a href="examples/run_multi_tool_agent.py">Runnable Example</a> ·
  <a href="LICENSE.md">License</a> ·
  <a href="SECURITY.md">Security</a>
</p>

`shipit_agent` is a standalone Python agent library for building tool-using, multi-step agents with clean runtime boundaries.

It is designed around a few principles:

- bring your own LLM
- keep tools explicit and typed
- make MCP a first-class integration surface
- support streaming events and session state
- keep the runtime small enough to understand and extend

This document is the long-form guide. Use [README.md](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/README.md) for quick-start examples and this file for deeper architecture, API, and integration details.

Project companion files:

- [README.md](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/README.md)
- [TOOLS.md](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/TOOLS.md)
- [LICENSE.md](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/LICENSE.md)
- [SECURITY.md](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/SECURITY.md)
- [notebooks/shipit_agent_test_drive.ipynb](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/notebooks/shipit_agent_test_drive.ipynb)

Notebook path:

- `notebooks/shipit_agent_test_drive.ipynb`

## Installation

Base install:

```bash
pip install shipit-agent
```

Local install from source:

```bash
pip install .
```

Editable local development install:

```bash
pip install -e .[dev]
```

Using `requirements.txt`:

```bash
pip install -r requirements.txt
```

Using Poetry:

```bash
poetry install
poetry run pytest -q
```

Optional extras:

```bash
pip install -e .[openai]
pip install -e .[anthropic]
pip install -e .[litellm]
pip install -e .[playwright]
pip install -e .[all]
```

Optional dependency groups:

- `openai`: OpenAI SDK adapter
- `anthropic`: Anthropic SDK adapter
- `litellm`: LiteLLM adapter, including Bedrock, Gemini, Groq, Together, Ollama, and other LiteLLM-backed providers
- `playwright`: Playwright browser support
- `all`: installs all optional groups

## One Complete Setup Example

This example shows a stronger real project setup with:

- AWS Bedrock using the DRKCACHE-style `gpt-oss-120b-1:0` model
- persistent memory
- persistent sessions
- persistent traces
- connector credentials
- built-in tools

If you want a runnable version with environment-based provider selection, use [examples/run_multi_tool_agent.py](examples/run_multi_tool_agent.py) together with [.env.example](.env.example).

```python
from shipit_agent import (
    Agent,
    CredentialRecord,
    FileCredentialStore,
    FileMemoryStore,
    FileSessionStore,
    FileTraceStore,
)
from shipit_agent.llms import BedrockChatLLM

credential_store = FileCredentialStore(".shipit_workspace/credentials.json")
credential_store.set(
    CredentialRecord(
        key="gmail",
        provider="gmail",
        secrets={
            "access_token": "ACCESS_TOKEN",
            "refresh_token": "REFRESH_TOKEN",
            "client_id": "CLIENT_ID",
            "client_secret": "CLIENT_SECRET",
        },
    )
)

agent = Agent.with_builtins(
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
    workspace_root=".shipit_workspace",
    memory_store=FileMemoryStore(".shipit_workspace/memory.json"),
    session_store=FileSessionStore(".shipit_workspace/sessions"),
    trace_store=FileTraceStore(".shipit_workspace/traces"),
    credential_store=credential_store,
    session_id="ops-agent",
    trace_id="ops-agent-trace",
)

result = agent.run(
    "Search for context, inspect email if needed, plan the work, "
    "and save the result as an artifact."
)

print(result.output)
```

## LLM Provider Setup Examples

The easiest way to run the example script is:

```bash
cp .env.example .env
python examples/run_multi_tool_agent.py "Use the tools, inspect the workspace, and summarize what matters."
```

The script reads `.env` automatically and chooses the provider from `SHIPIT_LLM_PROVIDER`.

### `.env` Template For The Runnable Script

```env
SHIPIT_LLM_PROVIDER=bedrock
SHIPIT_BEDROCK_MODEL=bedrock/openai.gpt-oss-120b-1:0
AWS_REGION_NAME=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
SHIPIT_WEB_SEARCH_PROVIDER=duckduckgo
SHIPIT_SESSION_ID=demo-session
SHIPIT_TRACE_ID=demo-trace
SHIPIT_WORKSPACE_ROOT=.shipit_workspace
```

`duckduckgo` is the default because it works without browser setup. Use `playwright` only when JavaScript-rendered search results or browser-grade navigation matter, and then install:

```bash
pip install -e .[playwright]
playwright install
```

If you already use a local AWS profile, you can replace `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` with `AWS_PROFILE=my-profile`.

Provider-specific variables:

- Bedrock: `AWS_REGION_NAME` or `AWS_DEFAULT_REGION`, plus either `AWS_PROFILE` or normal AWS credentials.
- OpenAI: `OPENAI_API_KEY` and optionally `SHIPIT_OPENAI_MODEL`.
- Anthropic: `ANTHROPIC_API_KEY` and optionally `SHIPIT_ANTHROPIC_MODEL`.
- Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY`, plus optionally `SHIPIT_GEMINI_MODEL`.
- Groq: `GROQ_API_KEY` and optionally `SHIPIT_GROQ_MODEL`.
- Together: `TOGETHERAI_API_KEY` or `TOGETHER_API_KEY`, plus optionally `SHIPIT_TOGETHER_MODEL`.
- Ollama: `OLLAMA_API_BASE` if you are not using the default local endpoint, plus optionally `SHIPIT_OLLAMA_MODEL`.

### AWS Bedrock

DRKCACHE uses Bedrock with the `gpt-oss-120b` family. The full LiteLLM model string is:

```python
from shipit_agent import Agent
from shipit_agent.llms import BedrockChatLLM

agent = Agent(
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
)
```

### OpenAI

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(llm=OpenAIChatLLM(model="gpt-4o-mini"))
```

### Anthropic

```python
from shipit_agent import Agent
from shipit_agent.llms import AnthropicChatLLM

agent = Agent(llm=AnthropicChatLLM(model="claude-3-5-sonnet-latest"))
```

### Gemini

```python
from shipit_agent import Agent
from shipit_agent.llms import GeminiChatLLM

agent = Agent(llm=GeminiChatLLM(model="gemini/gemini-1.5-pro"))
```

### Groq

```python
from shipit_agent import Agent
from shipit_agent.llms import GroqChatLLM

agent = Agent(llm=GroqChatLLM())
```

### Together

```python
from shipit_agent import Agent
from shipit_agent.llms import TogetherChatLLM

agent = Agent(llm=TogetherChatLLM())
```

### Ollama

```python
from shipit_agent import Agent
from shipit_agent.llms import OllamaChatLLM

agent = Agent(llm=OllamaChatLLM(model="ollama/llama3.1"))
```

## Package Overview

High-level package areas:

- `shipit_agent/agent.py`: public `Agent` entrypoint
- `shipit_agent/runtime.py`: core execution loop
- `shipit_agent/tools/`: built-in tools and tool abstractions
- `shipit_agent/integrations/`: connector credentials and third-party integration primitives
- `shipit_agent/mcp.py`: MCP transports, remote tool discovery, and MCP tool wrappers
- `shipit_agent/llms/`: model adapters
- `shipit_agent/stores/`: session and memory storage
- `shipit_agent/policies.py`: retry and routing policies
- `shipit_agent/prompts/`: default system prompt and prompt compatibility exports
- `shipit_agent/profiles.py`: reusable agent profile builder

## Core Concepts

### Agent

`Agent` is the main public API. It combines:

- an LLM
- a system prompt
- local tools
- MCP servers
- runtime policies
- optional memory and session stores

Basic usage:

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(llm=SimpleEchoLLM())
result = agent.run("Hello")
print(result.output)
```

The `Agent` object can also be seeded with prior conversation history directly through `history=[Message(...)]`, or it can load persisted history through `session_store` and `session_id`.

Project chat-style usage:

```python
from shipit_agent import Agent, Message
from shipit_agent.llms import BedrockChatLLM

agent = Agent.with_builtins(
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
    session_id="project-chat",
    workspace_root=".shipit_workspace",
)

def chat(question: str):
    result = agent.run(question)
    return {
        "answer": result.output,
        "tool_results": [item.output for item in result.tool_results],
        "events": [(event.type, event.message) for event in result.events],
    }
```

Chat integration notes:

- keep a stable `session_id` per conversation
- keep one `workspace_root` per project or tenant
- use `history=[Message(...)]` only when you need to seed prior context manually
- prefer `session_store` for real product chat persistence

### LLM

An LLM is any object implementing the completion protocol used by the runtime.

Built-in adapters:

- `OpenAIChatLLM`
- `AnthropicChatLLM`
- `LiteLLMChatLLM`
- `BedrockChatLLM`
- `GeminiChatLLM`
- `GroqChatLLM`
- `TogetherChatLLM`
- `OllamaChatLLM`
- `SimpleEchoLLM`

### Tool

A tool exposes:

- `name`
- `description`
- `prompt`
- `prompt_instructions`
- `schema()`
- `run(context, **kwargs)`

The runtime passes tool schemas to the LLM and executes returned tool calls.

### MCP Server

MCP support exists in two forms:

- local/static MCP tool registration through `MCPServer`
- dynamic remote tool discovery through `RemoteMCPServer`

### Runtime Policies

`shipit_agent` exposes two policy objects:

- `RetryPolicy`: LLM retry and tool retry behavior
- `RouterPolicy`: automatic planning behavior for complex prompts

### Diagnostics

Use `agent.doctor()` when you want to verify setup before sending a real task through the runtime.

It checks:

- provider environment variables
- tool uniqueness
- MCP attachment count
- memory, session, and trace stores
- connector credential coverage
- runtime iteration budget

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(llm=SimpleEchoLLM())
report = agent.doctor()
print(report.to_markdown())
```

## Default Agent Prompt

If you do not provide a prompt, `Agent` uses `DEFAULT_AGENT_PROMPT`.

That default prompt is designed to:

- push the agent toward end-to-end execution
- prefer tools when they improve quality
- encourage verification
- avoid repeated failed actions

Example:

```python
from shipit_agent import Agent, DEFAULT_AGENT_PROMPT
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(llm=SimpleEchoLLM())
assert agent.prompt == DEFAULT_AGENT_PROMPT
```

## Quick Start Patterns

### 1. Minimal Agent

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(llm=SimpleEchoLLM())
result = agent.run("Summarize this project.")
print(result.output)
```

### 2. Built-In Agent

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(
    llm=SimpleEchoLLM(),
    workspace_root=".shipit_workspace",
    web_search_provider="duckduckgo",
)
```

### 3. Profile-Based Agent

```python
from shipit_agent import AgentProfileBuilder, FunctionTool
from shipit_agent.llms import SimpleEchoLLM


def add(a: int, b: int) -> str:
    return str(a + b)


agent = (
    AgentProfileBuilder("assistant")
    .description("General assistant")
    .tool(FunctionTool.from_callable(add))
    .build(llm=SimpleEchoLLM())
)
```

## Creating Custom Tools

There are two normal ways to create tools.

### FunctionTool

Use `FunctionTool` when a callable already models the capability clearly.

```python
from shipit_agent import FunctionTool


def title_case(text: str) -> str:
    """Convert text to title case."""
    return text.title()


tool = FunctionTool.from_callable(
    title_case,
    name="title_case",
    description="Convert text into title case.",
)
```

Best for:

- deterministic utilities
- formatting helpers
- small internal project operations

### Full Custom Tool Class

Use a custom class when you need:

- custom schema
- structured metadata
- custom prompt guidance
- external service integration

```python
from shipit_agent.tools.base import ToolContext, ToolOutput


class WordCountTool:
    name = "count_words"
    description = "Count words in a string."
    prompt = "Use this for deterministic word counts."
    prompt_instructions = "Prefer this over estimating counts in prose."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to count"},
                    },
                    "required": ["text"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        text = kwargs["text"]
        count = len(text.split())
        return ToolOutput(
            text=str(count),
            metadata={"word_count": count},
        )
```

## Built-In Tools

Current built-in tools include:

- `WebSearchTool`
- `OpenURLTool`
- `PlaywrightBrowserTool`
- `AskUserTool`
- `HumanReviewTool`
- `MemoryTool`
- `PlannerTool`
- `PromptTool`
- `VerifierTool`
- `ToolSearchTool`
- `ArtifactBuilderTool`
- `WorkspaceFilesTool`
- `CodeExecutionTool`
- `GmailTool`
- `GoogleCalendarTool`
- `GoogleDriveTool`
- `SlackTool`
- `LinearTool`
- `JiraTool`
- `NotionTool`
- `ConfluenceTool`
- `CustomAPITool`
- `SubAgentTool` when an LLM is supplied to `Agent.with_builtins(...)`

### WebSearchTool

Purpose:

- current information
- search result gathering
- source discovery

When to use it:

- the answer may depend on fresh or changing information
- you need candidate sources before opening specific pages
- you want provider-backed web discovery inside the agent loop

Provider modes:

- `duckduckgo`
- `playwright`
- `brave`
- `serper`
- `tavily`

Example:

```python
from shipit_agent import WebSearchTool

search = WebSearchTool(provider="duckduckgo")
```

### OpenURLTool

Purpose:

- read a known URL directly
- inspect page content after search

When to use it:

- the user already gave a specific URL
- search results found a likely source and you now need the page contents
- you want direct page text rather than search snippets

Example:

```python
from shipit_agent import OpenURLTool

tool = OpenURLTool()
```

### PlaywrightBrowserTool

Purpose:

- render JavaScript-heavy pages
- read browser-resolved page content

When to use it:

- a plain HTTP fetch is not enough
- the page relies on client-side rendering
- browser-like loading behavior matters for the result

This degrades gracefully if Playwright is not installed.
For the cleanest first-run experience, keep Playwright as an opt-in tool rather than the default search path.

### AskUserTool

Purpose:

- request structured clarification from the human

Use it when ambiguity materially changes the result.

Typical usage:

- choosing between scopes or output formats
- selecting one of several valid strategies
- collecting a missing identifier or preference

### HumanReviewTool

Purpose:

- explicit approval gates before consequential actions

Use it for approve/edit/reject flows, not normal clarification.

Typical usage:

- before sending an email or Slack message
- before creating or modifying project records
- before publishing a generated artifact

### MemoryTool

Purpose:

- store durable facts
- search remembered facts later

Typical usage:

- saving stable user preferences
- remembering IDs, links, or project-specific facts
- searching prior remembered context before asking again

### PlannerTool

Purpose:

- break down complex work into steps

The runtime can also invoke planning automatically through `RouterPolicy`.

Typical usage:

- multi-stage build or research tasks
- tasks with multiple tools and dependencies
- long requests where the agent should decompose the work before acting

### PromptTool

Purpose:

- build prompts for downstream agents, roles, or workflows

Typical usage:

- generating a clean system prompt
- refining a role prompt for a specialized agent
- converting a rough instruction set into an operational prompt

### VerifierTool

Purpose:

- check content against explicit criteria

Typical usage:

- final output validation
- checking whether required terms or conditions are present
- quality gating before return or publish steps

### ToolSearchTool

Purpose:

- search available tools when the right capability is unclear

Typical usage:

- large agent profiles with many tools
- selecting the best tool before a complex action
- inspecting capability coverage inside the runtime

### ArtifactBuilderTool

Purpose:

- create named artifacts
- optionally export them to files

Example:

```python
from shipit_agent import ArtifactBuilderTool

tool = ArtifactBuilderTool(workspace_root=".shipit_workspace/artifacts")
```

Typical usage:

- reports
- summaries saved to files
- reusable artifacts produced by tool or model output

### WorkspaceFilesTool

Purpose:

- read
- write
- append
- list
- create directories

This is the standard file workspace tool for local workflows.

Typical usage:

- write a generated report
- inspect a file before editing
- save intermediate outputs used by later steps

### CodeExecutionTool

Purpose:

- run local code in subprocesses
- support deterministic computation
- support script-based validation

Supported interpreter families:

- `python`
- `bash`
- `sh`
- `zsh`
- `javascript`
- `typescript`
- `ruby`
- `php`
- `perl`
- `lua`
- `r`

Language aliases supported:

- `python3` -> `python`
- `py` -> `python`
- `shell` -> `bash`
- `node` -> `javascript`
- `js` -> `javascript`
- `ts` -> `typescript`

Important note:

- `CodeExecutionTool` only runs interpreters that are actually installed on the machine

Example:

```python
from shipit_agent import CodeExecutionTool

tool = CodeExecutionTool(workspace_root=".shipit_workspace/code")
```

Typical usage:

- calculations
- parsing and transformations
- small scripts
- deterministic checks the model should not guess

### GmailTool

Purpose:

- search Gmail inbox contents
- retrieve recent or unread email previews
- integrate connected Google account context into an agent workflow

Example:

```python
from shipit_agent import Agent, CredentialRecord, FileCredentialStore, GmailTool
from shipit_agent.llms import SimpleEchoLLM

credential_store = FileCredentialStore(".shipit_workspace/credentials.json")
credential_store.set(
    CredentialRecord(
        key="gmail",
        provider="gmail",
        secrets={
            "access_token": "ACCESS_TOKEN",
            "refresh_token": "REFRESH_TOKEN",
            "client_id": "CLIENT_ID",
            "client_secret": "CLIENT_SECRET",
        },
    )
)

agent = Agent(
    llm=SimpleEchoLLM(),
    credential_store=credential_store,
    tools=[GmailTool()],
)
```

This tool expects the Google API client libraries to be installed when used.

Main actions:

- `search`
- `read_message`
- `read_thread`
- `list_labels`
- `create_draft`
- `send_message`

Typical usage:

- find recent unread mail
- inspect a specific thread
- draft or send a message after human review

### GoogleCalendarTool

Purpose:

- search and list Google Calendar events
- inspect upcoming schedule context

Main actions:

- `list_events`

Typical usage:

- check upcoming meetings
- find events that match a topic or keyword
- pull schedule context before planning work

### GoogleDriveTool

Purpose:

- search Google Drive files
- retrieve Drive file metadata and links

Main actions:

- `search_files`

Typical usage:

- locate docs, slides, spreadsheets, or folders in Drive
- find a file before linking or summarizing it

### SlackTool

Purpose:

- search Slack content
- list channels
- post messages

Main actions:

- `search_messages`
- `post_message`
- `list_channels`

Typical usage:

- find a prior conversation
- send a team update after approval
- discover the correct channel before posting

### LinearTool

Purpose:

- search Linear issues
- create new Linear issues

Main actions:

- `search_issues`
- `create_issue`

Typical usage:

- find bugs or tasks by title
- create a follow-up issue from agent research

### JiraTool

Purpose:

- search Jira issues
- create Jira issues

Main actions:

- `search_issues`
- `create_issue`

Typical usage:

- search tickets using JQL
- create operational tasks or bug tickets

### NotionTool

Purpose:

- search Notion pages
- create Notion pages

Main actions:

- `search_pages`
- `create_page`

Typical usage:

- find internal notes or docs
- create a project note or working page

### ConfluenceTool

Purpose:

- search Confluence content
- create Confluence pages

Main actions:

- `search_pages`
- `create_page`

Typical usage:

- find wiki documentation
- publish a generated page into a space

### CustomAPITool

Purpose:

- call a configured internal or third-party HTTP API
- act as a generic connector when a dedicated tool does not exist yet

Main inputs:

- `method`
- `path`
- `query`
- `body`

Typical usage:

- internal back-office APIs
- private services
- temporary integrations before promoting them into dedicated tools

### SubAgentTool

Purpose:

- delegate a narrow sub-task to the same underlying model interface

Best used for:

- summarization
- focused analysis
- bounded side work

## Using Multiple Tools Together

A stronger setup usually mixes several tool types in one agent:

- built-in tools for web search, browsing, file access, planning, memory, and artifacts
- your own `FunctionTool` helpers for project-specific actions
- MCP-discovered tools for remote systems

The runnable example follows exactly this pattern. It builds the built-in registry with `get_builtin_tools(...)` and then appends local function tools for project context and arithmetic.

```python
from shipit_agent import Agent, FunctionTool, get_builtin_tools
from shipit_agent.llms import BedrockChatLLM

def project_context() -> str:
    return "Describe the local engineering context for this workspace."

def add_numbers(a: int, b: int) -> str:
    return str(a + b)

llm = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
tools = get_builtin_tools(llm=llm, workspace_root=".shipit_workspace")
tools.extend([
    FunctionTool.from_callable(project_context, name="project_context"),
    FunctionTool.from_callable(add_numbers, name="add_numbers"),
])

agent = Agent(llm=llm, tools=tools)
```

One agent can use many tools at once.

```python
from shipit_agent import Agent, CodeExecutionTool, FunctionTool, WebSearchTool, WorkspaceFilesTool
from shipit_agent.llms import SimpleEchoLLM


def extract_keywords(text: str) -> str:
    words = [word.strip(".,").lower() for word in text.split()]
    return ", ".join(sorted(set(word for word in words if len(word) > 5)))


agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[
        WebSearchTool(provider="duckduckgo"),
        WorkspaceFilesTool(root_dir=".shipit_workspace"),
        CodeExecutionTool(workspace_root=".shipit_workspace/code"),
        FunctionTool.from_callable(extract_keywords, name="extract_keywords"),
    ],
)
```

That agent can:

- search external sources
- run code locally
- save outputs
- use deterministic project-specific helpers

## MCP Support

### Static MCPServer

Use `MCPServer` when you already have MCP-compatible tools wrapped locally.

```python
from shipit_agent import MCPServer, MCPTool

mcp = MCPServer(name="demo").register(
    MCPTool(
        name="lookup",
        description="Lookup data",
        handler=lambda context, **kwargs: "ok",
    )
)
```

### RemoteMCPServer

Use `RemoteMCPServer` for dynamic discovery from a remote MCP endpoint.

Transport options:

- `MCPHTTPTransport`
- `MCPSubprocessTransport`
- `PersistentMCPSubprocessTransport`

HTTP example:

```python
from shipit_agent import MCPHTTPTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="docs",
    transport=MCPHTTPTransport("http://localhost:8080/mcp"),
)
```

Subprocess example:

```python
from shipit_agent import MCPSubprocessTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="local_docs",
    transport=MCPSubprocessTransport(["python", "my_mcp_server.py"]),
)
```

Persistent subprocess example:

```python
from shipit_agent import PersistentMCPSubprocessTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="local_docs",
    transport=PersistentMCPSubprocessTransport(["python", "my_mcp_server.py"]),
)
```

When a `RemoteMCPServer` is attached, the registry discovers remote tools and exposes them like normal tools.

## Using Local Tools And MCP Together

You can combine local built-ins, your own tools, and MCP-discovered tools in the same agent. This is one of the main runtime strengths of `shipit_agent`.

```python
from shipit_agent import Agent, MCPHTTPTransport, RemoteMCPServer, FunctionTool, get_builtin_tools
from shipit_agent.llms import BedrockChatLLM

def project_context() -> str:
    return "Return local context for this repo."

llm = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
remote_mcp = RemoteMCPServer(MCPHTTPTransport(base_url="http://127.0.0.1:8080"))

agent = Agent(
    llm=llm,
    tools=[
        *get_builtin_tools(llm=llm, workspace_root=".shipit_workspace"),
        FunctionTool.from_callable(project_context, name="project_context"),
    ],
    mcps=[remote_mcp],
)
```

```python
from shipit_agent import Agent, MCPHTTPTransport, RemoteMCPServer, WebSearchTool, WorkspaceFilesTool
from shipit_agent.llms import SimpleEchoLLM

mcp = RemoteMCPServer(
    name="design_system",
    transport=MCPHTTPTransport("http://localhost:8080/mcp"),
)

agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[
        WebSearchTool(provider="duckduckgo"),
        WorkspaceFilesTool(root_dir=".shipit_workspace"),
    ],
    mcps=[mcp],
)
```

This lets one runtime combine:

- built-in local tools
- custom project tools
- dynamically discovered MCP tools

## Streaming Events

The runnable example also supports streamed runtime events by setting `SHIPIT_STREAM=1`.

```bash
SHIPIT_STREAM=1 python examples/run_multi_tool_agent.py "Research the task, use tools, and explain each step."
```

Use `stream()` when you want step-level visibility.

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(llm=SimpleEchoLLM())

for event in agent.stream("Investigate this issue and use tools if needed."):
    print(event.type, event.message, event.payload)
```

If you need JSON-friendly packets for an API or UI layer:

```python
for event in agent.stream("Investigate this issue and use tools if needed."):
    packet = event.to_dict()
    print(packet)
```

Streaming event reference:

| Event Type            | Meaning                                                       | Common Payload Fields           |
| --------------------- | ------------------------------------------------------------- | ------------------------------- |
| `run_started`         | Agent accepted the prompt and initialized state.              | `prompt`                        |
| `planning_started`    | Planner tool execution started.                               | `prompt`                        |
| `planning_completed`  | Planner tool finished.                                        | `output`                        |
| `step_started`        | A new LLM step began.                                         | `iteration`, `tool_count`       |
| `tool_called`         | A tool call was issued by the model.                          | `arguments`, `iteration`        |
| `tool_completed`      | A tool finished successfully.                                 | `output`, `iteration`           |
| `tool_failed`         | A tool exhausted retries and failed.                          | `error`, `iteration`            |
| `tool_retry`          | A tool is being retried after an error.                       | `attempt`, `error`, `iteration` |
| `llm_retry`           | The LLM call is being retried.                                | `attempt`, `error`              |
| `interactive_request` | A human-in-the-loop tool asked for approval or clarification. | `kind`, `payload`               |
| `mcp_attached`        | An MCP server was attached to the run.                        | `server`                        |
| `run_completed`       | The run finished and final output is available.               | `output`                        |

Typical streaming output loop:

```python
for event in agent.stream("Research the issue and explain each step."):
    print(f"[{event.type}] {event.message}")
    if event.payload:
        print(event.payload)
```

Concrete packet examples:

Tool packet:

```python
{
    "type": "tool_called",
    "message": "Tool called: slack",
    "payload": {
        "arguments": {
            "action": "channel_history",
            "channel": "C123456",
        },
        "iteration": 1,
    },
}
```

MCP packet:

```python
{
    "type": "mcp_attached",
    "message": "MCP server attached: docs",
    "payload": {
        "server": "docs",
    },
}
```

Interactive tool packet:

```python
{
    "type": "interactive_request",
    "message": "Interactive request from human_review",
    "payload": {
        "kind": "human_review",
        "payload": {
            "interactive": True,
            "kind": "human_review",
        },
    },
}
```

Completion packet:

```python
{
    "type": "run_completed",
    "message": "Agent run completed",
    "payload": {
        "output": "Final answer text here.",
    },
}
```

Final run shape:

```python
result = agent.run("Investigate the issue.")
payload = result.to_dict()
```

Chat session wrapper:

```python
session = agent.chat_session(session_id="project-chat")
reply = session.send("Summarize the current workspace.")
history = session.history()
```

WebSocket packets:

```python
for packet in session.stream_packets(
    "Plan the work and show packet updates.",
    transport="websocket",
):
    print(packet)
```

SSE packets:

```python
for packet in session.stream_packets(
    "Explain the runtime in SSE packet form.",
    transport="sse",
):
    print(packet)
```

## Runtime Policies

### RetryPolicy

Controls retry behavior for:

- LLM calls
- tool execution

Example:

```python
from shipit_agent import RetryPolicy

policy = RetryPolicy(
    max_llm_retries=2,
    max_tool_retries=1,
)
```

### RouterPolicy

Controls runtime planning behavior.

Example:

```python
from shipit_agent import RouterPolicy

policy = RouterPolicy(
    auto_plan=True,
    long_prompt_threshold=80,
)
```

The router currently supports:

- automatic plan triggering for complex prompts
- keyword-based planning heuristics

## Storage

Built-in stores:

- `InMemoryMemoryStore`
- `InMemorySessionStore`
- `FileMemoryStore`
- `FileSessionStore`

Connector credential stores:

- `InMemoryCredentialStore`
- `FileCredentialStore`

These let the runtime:

- persist prior messages by `session_id`
- persist tool results as memory facts

History can also be supplied directly when constructing an agent:

```python
from shipit_agent import Agent, Message
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    history=[
        Message(role="user", content="We already decided to use Gmail and Slack."),
        Message(role="assistant", content="I will keep those integrations in scope."),
    ],
)
```

Example:

```python
from shipit_agent import Agent, InMemoryMemoryStore, InMemorySessionStore
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    memory_store=InMemoryMemoryStore(),
    session_store=InMemorySessionStore(),
    session_id="demo-session",
)
```

Persistent file-backed stores:

```python
from shipit_agent import Agent, FileMemoryStore, FileSessionStore
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    memory_store=FileMemoryStore(".shipit_workspace/memory.json"),
    session_store=FileSessionStore(".shipit_workspace/sessions"),
    session_id="project-session",
)
```

Credential store example:

```python
from shipit_agent import CredentialRecord, FileCredentialStore

store = FileCredentialStore(".shipit_workspace/credentials.json")
store.set(
    CredentialRecord(
        key="gmail",
        provider="gmail",
        secrets={"access_token": "..."},
    )
)
```

## Model Adapters

### OpenAI

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(llm=OpenAIChatLLM(model="gpt-4o-mini"))
```

### Anthropic

```python
from shipit_agent import Agent
from shipit_agent.llms import AnthropicChatLLM

agent = Agent(llm=AnthropicChatLLM(model="claude-3-5-sonnet-latest"))
```

### LiteLLM Generic

```python
from shipit_agent import Agent
from shipit_agent.llms import LiteLLMChatLLM

agent = Agent(llm=LiteLLMChatLLM(model="groq/llama-3.3-70b-versatile"))
```

### LiteLLM Convenience Wrappers

```python
from shipit_agent import Agent
from shipit_agent.llms import BedrockChatLLM, GeminiChatLLM, GroqChatLLM, OllamaChatLLM, TogetherChatLLM

bedrock_agent = Agent(llm=BedrockChatLLM())
gemini_agent = Agent(llm=GeminiChatLLM())
groq_agent = Agent(llm=GroqChatLLM())
ollama_agent = Agent(llm=OllamaChatLLM())
together_agent = Agent(llm=TogetherChatLLM())
```

## End-To-End Example

This is a fuller example showing built-ins, MCP, artifacts, and workspace usage together.

```python
from shipit_agent import Agent, MCPHTTPTransport, RemoteMCPServer
from shipit_agent.llms import OpenAIChatLLM

mcp = RemoteMCPServer(
    name="project_docs",
    transport=MCPHTTPTransport("http://localhost:8080/mcp"),
)

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    mcps=[mcp],
    workspace_root=".shipit_workspace",
    web_search_provider="brave",
    web_search_api_key="BRAVE_API_KEY",
    metadata={
        "workspace_root": ".shipit_workspace",
        "artifact_workspace_root": ".shipit_workspace/artifacts",
    },
)

result = agent.run(
    "Research the latest approach, inspect remote docs through MCP, "
    "write a summary file, and generate a final artifact."
)

print(result.output)
```

## CLI

There is also a simple CLI entrypoint:

```bash
shipit "Hello from shipit_agent"
shipit --json "Run the agent and print events"
```

The CLI currently uses `SimpleEchoLLM` and is intended as a lightweight smoke-test interface.

## API Reference

### Agent

Main public runtime entrypoint.

Constructor fields:

| Field              | Type                      | Purpose                                              |
| ------------------ | ------------------------- | ---------------------------------------------------- |
| `llm`              | `Any`                     | Model adapter used for completions.                  |
| `prompt`           | `str`                     | System prompt. Defaults to `DEFAULT_AGENT_PROMPT`.   |
| `tools`            | `list[Any]`               | Local tool objects exposed to the runtime.           |
| `mcps`             | `list[Any]`               | MCP servers attached to the run.                     |
| `name`             | `str`                     | Agent name used in metadata and tracing.             |
| `description`      | `str`                     | Human-readable role description.                     |
| `metadata`         | `dict[str, Any]`          | Extra runtime metadata passed into events and tools. |
| `history`          | `list[Message]`           | Seeded prior conversation history.                   |
| `memory_store`     | `MemoryStore \| None`     | Memory backend for tool-result facts.                |
| `session_store`    | `SessionStore \| None`    | Session backend for persisted chat history.          |
| `credential_store` | `CredentialStore \| None` | Connector credential backend.                        |
| `trace_store`      | `TraceStore \| None`      | Event tracing backend.                               |
| `session_id`       | `str \| None`             | Session identifier used by the session store.        |
| `trace_id`         | `str \| None`             | Trace identifier used by the trace store.            |
| `max_iterations`   | `int`                     | Maximum multi-step runtime loop depth.               |
| `retry_policy`     | `RetryPolicy`             | Retry behavior for LLM and tool execution.           |
| `router_policy`    | `RouterPolicy`            | Automatic planning behavior.                         |

Methods:

| Method                | Purpose                                            |
| --------------------- | -------------------------------------------------- |
| `run(user_prompt)`    | Execute a full agent run and return `AgentResult`. |
| `stream(user_prompt)` | Return step-level events for the run.              |
| `doctor(env=None)`    | Produce a local diagnostics report before running. |
| `with_builtins(...)`  | Build an agent with the prebuilt tool catalog.     |

Recommended field combinations:

| Scenario             | Recommended Fields                                                                                  |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| Local smoke test     | `llm`, `tools` or `with_builtins(...)`                                                              |
| Project chat app     | `llm`, `session_store`, `session_id`, `workspace_root`, `credential_store`                          |
| Research agent       | `llm`, `tools`, `mcps`, `trace_store`, `router_policy`                                              |
| Persistent ops agent | `llm`, `memory_store`, `session_store`, `trace_store`, `credential_store`, `session_id`, `trace_id` |

### AgentProfileBuilder

Fluent builder for reusable agent profiles.

Methods:

| Method                  | Purpose                                  |
| ----------------------- | ---------------------------------------- |
| `prompt(value)`         | Set the system prompt.                   |
| `description(value)`    | Set the profile description.             |
| `tool(value)`           | Attach one local tool.                   |
| `tools(values)`         | Attach multiple local tools.             |
| `mcp(value)`            | Attach one MCP server.                   |
| `mcps(values)`          | Attach multiple MCP servers.             |
| `metadata(**kwargs)`    | Add reusable metadata.                   |
| `max_iterations(value)` | Set the runtime loop depth.              |
| `retry_policy(value)`   | Override retry behavior.                 |
| `router_policy(value)`  | Override auto-planning behavior.         |
| `trace_store(value)`    | Attach a reusable trace backend.         |
| `build_profile()`       | Return a reusable `AgentProfile`.        |
| `build(llm=...)`        | Materialize an `Agent` from the profile. |

### RetryPolicy

Controls retry behavior for LLM and tool execution.

| Field                 | Purpose                                           |
| --------------------- | ------------------------------------------------- |
| `max_llm_retries`     | Maximum retries for model completion failures.    |
| `max_tool_retries`    | Maximum retries for tool execution failures.      |
| `retry_on_exceptions` | Exception tuple used to decide what is retryable. |

### RouterPolicy

Controls automatic planning behavior.

| Field Or Method         | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `auto_plan`             | Enable or disable planner auto-execution.            |
| `plan_keywords`         | Keywords that trigger planning.                      |
| `long_prompt_threshold` | Prompt length threshold that can trigger planning.   |
| `should_plan(prompt)`   | Decide whether the prompt should invoke the planner. |

### MCP Types

#### MCPServer

Static MCP tool container.

Methods:

- `register(tool)`
- `register_many(tools)`
- `discover_tools()`

#### RemoteMCPServer

Remote MCP server with dynamic discovery.

Methods:

- `initialize()`
- `discover_tools()`

| Type                               | Purpose                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| `MCPHTTPTransport`                 | HTTP JSON-RPC transport for remote MCP servers.                |
| `MCPSubprocessTransport`           | One-shot subprocess JSON-RPC transport.                        |
| `PersistentMCPSubprocessTransport` | Long-lived subprocess transport for persistent stdio sessions. |
| `MCPTool`                          | Static local MCP-compatible tool wrapper.                      |
| `MCPRemoteTool`                    | Remote dynamically discovered MCP tool wrapper.                |

### Stores

#### InMemoryMemoryStore

In-memory memory implementation.

Methods:

- `add(fact)`
- `search(query, limit=5)`

#### FileMemoryStore

JSON-backed persistent memory store.

Methods:

- `add(fact)`
- `search(query, limit=5)`

#### InMemorySessionStore

In-memory session message store.

Methods:

- `load(session_id)`
- `save(record)`

#### FileSessionStore

File-backed JSON session store.

Methods:

- `load(session_id)`
- `save(record)`

#### InMemoryCredentialStore

In-memory connector credential store.

Methods:

- `get(key)`
- `set(record)`
- `list()`

#### FileCredentialStore

JSON-backed credential store for third-party tools.

Methods:

- `get(key)`
- `set(record)`
- `list()`

Store summary:

| Store                     | Purpose                                           |
| ------------------------- | ------------------------------------------------- |
| `InMemoryMemoryStore`     | Temporary memory facts during a process lifetime. |
| `FileMemoryStore`         | Persistent memory facts on disk.                  |
| `InMemorySessionStore`    | Temporary chat history during a process lifetime. |
| `FileSessionStore`        | Persistent chat history on disk.                  |
| `InMemoryCredentialStore` | Temporary connector credentials in memory.        |
| `FileCredentialStore`     | Persistent connector credentials on disk.         |

### Tool Abstractions

#### FunctionTool

Wraps a Python callable as a tool.

Important methods:

- `from_callable(...)`
- `schema()`
- `run(context, **kwargs)`

#### ToolContext

Runtime context passed to tools.

Fields:

- `prompt`
- `system_prompt`
- `metadata`
- `state`
- `session_id`

#### ToolOutput

Normalized tool output object.

Fields:

- `text`
- `metadata`

Shared tool contract:

| Field Or Method          | Purpose                                                   |
| ------------------------ | --------------------------------------------------------- |
| `name`                   | Unique model-facing tool name.                            |
| `description`            | Short capability summary for the model.                   |
| `prompt`                 | Default per-tool prompt guidance.                         |
| `prompt_instructions`    | Additional usage instructions merged into the tool block. |
| `schema()`               | JSON schema exposed to the model.                         |
| `run(context, **kwargs)` | Execute the tool and return `ToolOutput`.                 |

### Built-In Tools Reference

| Tool                    | Main Purpose                               | Main Fields                                                               | Common Actions Or Notes                                                                                             |
| ----------------------- | ------------------------------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `WebSearchTool`         | Provider-backed web search.                | `provider`, `api_key`, `provider_config`, `name`, `description`, `prompt` | Choose provider with `playwright`, `duckduckgo`, `brave`, `serper`, or `tavily`.                                    |
| `OpenURLTool`           | Fetch and extract content from a URL.      | `timeout`, `max_chars`, `user_agent`                                      | Good for direct page reading after search.                                                                          |
| `PlaywrightBrowserTool` | Browser-style page inspection.             | `name`, `description`, `prompt`                                           | Useful for rendered pages and browser actions.                                                                      |
| `AskUserTool`           | Request clarification from a human.        | `name`, `description`, `prompt`                                           | Emits interactive events.                                                                                           |
| `HumanReviewTool`       | Pause for approval or review.              | `name`, `description`, `prompt`                                           | Emits approval-oriented interactive events.                                                                         |
| `MemoryTool`            | Read and write memory facts.               | `name`, `description`, `prompt`                                           | Uses the configured memory store.                                                                                   |
| `PlannerTool`           | Create step-by-step plans.                 | `name`, `description`, `prompt`                                           | Works with `RouterPolicy` auto-planning.                                                                            |
| `PromptTool`            | Build prompts for downstream tasks.        | `name`, `description`, `prompt`                                           | Helpful for nested agents or reusable prompts.                                                                      |
| `VerifierTool`          | Evaluate output quality or completeness.   | `name`, `description`, `prompt`                                           | Good for self-check steps.                                                                                          |
| `ToolSearchTool`        | Search the available tool catalog.         | `name`, `description`, `prompt`                                           | Helps the model discover the right tool.                                                                            |
| `ArtifactBuilderTool`   | Build artifacts and export files.          | `workspace_root`, `name`, `description`, `prompt`                         | Supports file export to the artifact workspace.                                                                     |
| `WorkspaceFilesTool`    | Read and inspect local workspace files.    | `root_dir`, `name`, `description`, `prompt`                               | Operates under the configured workspace root.                                                                       |
| `CodeExecutionTool`     | Run local code in controlled interpreters. | `workspace_root`, `name`, `description`, `prompt`                         | Supports Python, shell, JS, TS, Ruby, PHP, Perl, Lua, and R if installed.                                           |
| `GmailTool`             | Gmail search and mail actions.             | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | `search`, `read_message`, `read_thread`, `get_attachment`, `list_labels`, `create_draft`, `send_message`            |
| `GoogleCalendarTool`    | Calendar lookup.                           | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | Event listing and scheduling workflows.                                                                             |
| `GoogleDriveTool`       | Drive file search.                         | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | File discovery across Drive.                                                                                        |
| `SlackTool`             | Slack discovery and messaging.             | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | `search_messages`, `post_message`, `list_channels`, `channel_history`, `get_thread_replies`, `user_lookup`          |
| `LinearTool`            | Linear issue and project workflows.        | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | `search_issues`, `create_issue`, `get_issue`, `update_issue`, `list_teams`, `list_projects`                         |
| `JiraTool`              | Jira ticket workflows.                     | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | `search_issues`, `create_issue`, `get_issue`, `list_transitions`, `transition_issue`, `add_comment`, `assign_issue` |
| `NotionTool`            | Notion page search and creation.           | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | Knowledge-base page workflows.                                                                                      |
| `ConfluenceTool`        | Confluence page search and creation.       | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | Wiki and documentation workflows.                                                                                   |
| `CustomAPITool`         | Call internal or third-party HTTP APIs.    | `credential_key`, `credential_store`, `name`, `description`, `prompt`     | Good for unsupported systems or internal services.                                                                  |
| `SubAgentTool`          | Delegate to another agent instance.        | `llm`, `name`, `description`, `prompt`                                    | Useful for contained sub-tasks when you want nested execution.                                                      |

Tool grouping summary:

| Group                 | Tools                                                                                                                                        |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Research and browsing | `WebSearchTool`, `OpenURLTool`, `PlaywrightBrowserTool`                                                                                      |
| Human in the loop     | `AskUserTool`, `HumanReviewTool`                                                                                                             |
| Planning and quality  | `PlannerTool`, `PromptTool`, `VerifierTool`, `ToolSearchTool`                                                                                |
| State and workspace   | `MemoryTool`, `ArtifactBuilderTool`, `WorkspaceFilesTool`, `CodeExecutionTool`                                                               |
| Connectors            | `GmailTool`, `GoogleCalendarTool`, `GoogleDriveTool`, `SlackTool`, `LinearTool`, `JiraTool`, `NotionTool`, `ConfluenceTool`, `CustomAPITool` |
| Delegation            | `SubAgentTool`                                                                                                                               |

Generic tool interface fields:

| Field                    | Meaning                                                |
| ------------------------ | ------------------------------------------------------ |
| `name`                   | Unique tool name exposed to the LLM.                   |
| `description`            | Short model-facing tool summary.                       |
| `prompt`                 | Default tool-specific prompt guidance.                 |
| `prompt_instructions`    | Additional usage rules added to the tool prompt block. |
| `schema()`               | JSON schema used for tool calling.                     |
| `run(context, **kwargs)` | Execution entrypoint.                                  |

Project integration recommendation:

- use `Agent.with_builtins(...)` to start quickly
- add local `FunctionTool` helpers for project-specific tasks
- attach MCP servers for remote systems
- use `agent.doctor()` before first live run

- `root_dir`
- `name`
- `description`
- `prompt`

#### CodeExecutionTool

Subprocess-based code execution tool.

Constructor highlights:

- `workspace_root`
- `timeout_seconds`
- `name`
- `description`
- `prompt`

Important methods:

- `supported_languages()`
- `schema()`
- `run(context, **kwargs)`

#### SubAgentTool

Delegates a narrow task to the configured LLM.

#### GmailTool

Connector-style Gmail search tool.

Constructor highlights:

- `credential_key`
- `credential_store`
- `name`
- `description`
- `prompt`

## Packaging Notes

Project metadata lives in [pyproject.toml](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/pyproject.toml).

Current package information:

- name: `shipit-agent`
- python: `>=3.11`
- script entrypoint: `shipit`
- optional extras for providers and Playwright

For publishing to PyPI, the normal flow is:

```bash
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## Testing

Testing and smoke-test assets:

- [examples/run_multi_tool_agent.py](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/examples/run_multi_tool_agent.py)
- [notebooks/shipit_agent_test_drive.ipynb](/Users/rahulraj/Documents/MYWORK/ai_developer/shipit_agent/notebooks/shipit_agent_test_drive.ipynb)

Run the test suite from the project root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q
```

Tests currently cover:

- core agent behavior
- tool construction and execution
- runtime policies
- state and storage
- MCP discovery
- prompt wiring
- web and browser tools
- code execution

## Current Scope

`shipit_agent` already supports:

- tool-aware agents
- multiple provider adapters
- streaming events
- local and remote MCP tools
- local code execution
- artifact export
- session and memory storage
- per-tool prompts

Areas that can be strengthened further:

- persistent long-lived MCP sessions
- richer planning and routing policies
- stronger sandbox controls for code execution
- more artifact types and export formats
- more provider-specific tool-calling normalization

## Summary

Use `shipit_agent` when you want:

- a clean Python agent runtime
- built-in tools without framework bloat
- first-class MCP support
- clear runtime events
- a codebase that is small enough to modify for your own product
