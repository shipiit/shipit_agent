<p align="center">
  <img src="shipit-icon.svg" alt="SHIPIT" width="120" height="120" />
</p>

<h1 align="center">SHIPIT Agent</h1>

<p align="center">
  <strong>A clean, powerful open-source Python agent library for building tool-using agents with MCP, browser workflows, local code execution, runtime policies, and structured streaming events.</strong>
</p>

<p align="center">
  <em>Build agents with local tools, remote MCP servers, memory, sessions, artifact generation, and multiple LLM providers through one consistent runtime.</em>
</p>

<p align="center">
  <a href="docs.md">Full docs</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#one-running-setup-example">Run an agent</a> ·
  <a href="#using-tools-and-mcp-together">Tools + MCP</a> ·
  <a href="#streaming-events">Streaming</a> ·
  <a href="#gmail-and-third-party-tools">Third-party tools</a> ·
  <a href="SECURITY.md">Security</a>
</p>

<p align="center">
  <em>Readable docs, explicit tools, and a runtime that is small enough to extend without fighting framework overhead.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue?style=for-the-badge" alt="Version" />
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-green?style=for-the-badge" alt="Python" />
  <img src="https://img.shields.io/badge/runtime-agent%20library-purple?style=for-the-badge" alt="Agent Runtime" />
  <img src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge" alt="License" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Anthropic-native-D77757?style=flat-square&logo=anthropic" alt="Anthropic" />
  <img src="https://img.shields.io/badge/AWS%20Bedrock-supported-orange?style=flat-square&logo=amazon-aws" alt="Bedrock" />
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
  <img src="https://img.shields.io/badge/Ollama-supported-black?style=flat-square" alt="Ollama" />
  <img src="https://img.shields.io/badge/Vertex%20AI-supported-34A853?style=flat-square&logo=googlecloud" alt="Vertex AI" />
  <img src="https://img.shields.io/badge/Together%20AI-supported-blue?style=flat-square" alt="Together" />
  <img src="https://img.shields.io/badge/Groq-supported-red?style=flat-square" alt="Groq" />
  <img src="https://img.shields.io/badge/OpenRouter-supported-black?style=flat-square" alt="OpenRouter" />
  <img src="https://img.shields.io/badge/Custom%20API-supported-gray?style=flat-square" alt="Custom" />
</p>

`shipit_agent` is a standalone Python agent library focused on a clean runtime:

- bring your own LLM
- attach Python tools
- attach MCP servers
- use prebuilt tools like web search, open URL, ask user, and human review
- support iterative multi-step tool loops
- support memory and session stores
- support OpenAI, Anthropic, and LiteLLM adapters
- support Bedrock, Gemini, Groq, Together, Ollama, and other LiteLLM-backed providers
- stream structured events
- inspect each step
- compose reusable agent profiles
- keep clean boundaries between runtime, tools, MCP, and profiles
- ship with a strong default system prompt and runtime policies
- support persistent file-backed session and memory stores
- support connector-style third-party tools such as Gmail
- support persistent MCP subprocess sessions

## Install

Published package:

```bash
pip install shipit-agent
```

Local package install:

```bash
pip install .
```

Editable development install:

```bash
pip install -e .[dev]
```

If you prefer `requirements.txt`:

```bash
pip install -r requirements.txt
```

If you use Poetry instead of pip:

```bash
poetry install
poetry run pytest -q
```

Playwright is optional. The default web search path uses `duckduckgo` and does not require browser binaries.
If you want browser-rendered search or page automation, install the extra and browser bundle:

```bash
pip install -e .[playwright]
playwright install
```

Long-form documentation:

- [docs.md](docs.md)
- [TOOLS.md](TOOLS.md)
- [SECURITY.md](SECURITY.md)
- [LICENSE.md](LICENSE.md)

Environment and examples:

- [.env.example](.env.example)
- [examples/run_multi_tool_agent.py](examples/run_multi_tool_agent.py)
- [notebooks/shipit_agent_test_drive.ipynb](notebooks/shipit_agent_test_drive.ipynb)

If you did not see the notebook earlier, the current path is:

- `notebooks/shipit_agent_test_drive.ipynb`

## One Running Setup Example

This is the simplest high-power setup pattern for a real project. If you want a runnable script instead of an inline snippet, start from [examples/run_multi_tool_agent.py](examples/run_multi_tool_agent.py) and copy [.env.example](.env.example) to `.env`.

This setup gives you:

- provider selection from environment variables
- built-in tools plus a few local function tools
- persistent memory, sessions, and traces
- a clean place to add your own prompt, MCP servers, and connector credentials

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
        key="slack",
        provider="slack",
        secrets={"token": "SLACK_BOT_TOKEN"},
    )
)

agent = Agent.with_builtins(
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
    workspace_root=".shipit_workspace",
    memory_store=FileMemoryStore(".shipit_workspace/memory.json"),
    session_store=FileSessionStore(".shipit_workspace/sessions"),
    trace_store=FileTraceStore(".shipit_workspace/traces"),
    credential_store=credential_store,
    session_id="project-agent",
    trace_id="project-agent-run",
)

result = agent.run("Research the task, use tools, and keep the project context.")
print(result.output)
```

## Environment Setup For Scripts

The runnable example reads `.env` automatically. Start by copying the template:

```bash
cp .env.example .env
```

For AWS Bedrock with the DRKCACHE-style model, set at least these values:

```env
SHIPIT_LLM_PROVIDER=bedrock
SHIPIT_BEDROCK_MODEL=bedrock/openai.gpt-oss-120b-1:0
AWS_REGION_NAME=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

You can also use `AWS_PROFILE` instead of inline AWS keys if your local AWS CLI profile is already configured. Other providers use their standard SDK environment variables, for example `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, or `TOGETHERAI_API_KEY`.

For web search, the default is now:

```env
SHIPIT_WEB_SEARCH_PROVIDER=duckduckgo
```

If you want browser-backed search and browser automation, switch to:

```env
SHIPIT_WEB_SEARCH_PROVIDER=playwright
```

and install Playwright plus its browser bundle:

```bash
pip install -e .[playwright]
playwright install
```

Run the example like this:

```bash
python examples/run_multi_tool_agent.py "Search the web, inspect the workspace, and summarize the result."
```

Enable streaming events with:

```bash
SHIPIT_STREAM=1 python examples/run_multi_tool_agent.py "Plan the work and explain each runtime step."
```

Use the notebook when you want an interactive setup and smoke-test workflow:

```bash
jupyter notebook notebooks/shipit_agent_test_drive.ipynb
```

## Agent Diagnostics

Use `agent.doctor()` to validate provider env, tool setup, MCP attachments, stores, and connector credentials before a real run.

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(llm=SimpleEchoLLM())
report = agent.doctor()
print(report.to_markdown())
```

## Project Chat Pattern

For app integration, keep one `Agent` instance tied to a `session_id` and call `run(...)` for each user message.

```python
from shipit_agent import Agent
from shipit_agent.llms import BedrockChatLLM

agent = Agent.with_builtins(
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
    session_id="project-chat",
    workspace_root=".shipit_workspace",
)

def chat(user_message: str) -> str:
    result = agent.run(user_message)
    return result.output
```

## Streaming Packet Shape

`agent.stream(...)` yields `AgentEvent` objects. Each event can be serialized with `event.to_dict()`.

Packet shape:

```python
{
    "type": "tool_completed",
    "message": "Tool completed: web_search",
    "payload": {
        "output": "...",
        "iteration": 1,
    },
}
```

Example:

```python
for event in agent.stream("Research the issue and explain each step."):
    print(event.to_dict())
```

Common packet examples:

`run_started`

```python
{
    "type": "run_started",
    "message": "Agent run started",
    "payload": {
        "prompt": "Research the issue and explain each step."
    },
}
```

`tool_called`

```python
{
    "type": "tool_called",
    "message": "Tool called: web_search",
    "payload": {
        "arguments": {"query": "latest incident response workflow"},
        "iteration": 1,
    },
}
```

`tool_completed`

```python
{
    "type": "tool_completed",
    "message": "Tool completed: workspace_files",
    "payload": {
        "output": "Found 12 matching files...",
        "iteration": 1,
    },
}
```

`mcp_attached`

```python
{
    "type": "mcp_attached",
    "message": "MCP server attached: docs",
    "payload": {
        "server": "docs"
    },
}
```

`interactive_request`

```python
{
    "type": "interactive_request",
    "message": "Interactive request from ask_user",
    "payload": {
        "kind": "ask_user",
        "payload": {"interactive": True, "kind": "ask_user"}
    },
}
```

`run_completed`

```python
{
    "type": "run_completed",
    "message": "Agent run completed",
    "payload": {
        "output": "Final answer text here."
    },
}
```

`AgentResult` is also serializable with `result.to_dict()` if you want one final packet containing the full run.

Chat-session wrapper example:

```python
session = agent.chat_session(session_id="project-chat")
reply = session.send("Summarize the current workspace.")

for packet in session.stream_packets(
    "Plan the work and show packet updates.",
    transport="websocket",
):
    print(packet)
```

SSE packet example:

```python
for packet in session.stream_packets(
    "Explain the runtime in SSE packet form.",
    transport="sse",
):
    print(packet)
```

## Quick Start

```python
from shipit_agent import Agent, AgentProfileBuilder, FunctionTool
from shipit_agent.llms import SimpleEchoLLM


def add(a: int, b: int) -> str:
    return str(a + b)


agent = (
    AgentProfileBuilder("assistant")
    .description("General purpose assistant")
    .prompt("You are concise, accurate, and tool-aware.")
    .tool(FunctionTool.from_callable(add, name="add"))
    .build(llm=SimpleEchoLLM())
)

result = agent.run("Hello")
print(result.output)
```

## Default Built-In Agent

If you want a capable agent quickly, start here:

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(
    llm=SimpleEchoLLM(),
    name="shipit",
    description="General-purpose execution agent",
    workspace_root=".shipit_workspace",
    web_search_provider="duckduckgo",
)

result = agent.run("Research the topic, plan the work, and save a summary.")
print(result.output)
```

## Session History And Memory

You can keep context in two ways:

- pass `history=[Message(...), ...]` to seed the agent with prior turns
- use `session_store` plus `session_id` to persist history across runs

```python
from shipit_agent import Agent, InMemorySessionStore, Message
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    history=[
        Message(role="user", content="We are building an incident response workflow."),
        Message(role="assistant", content="Understood. I will keep the design focused on operations."),
    ],
    session_store=InMemorySessionStore(),
    session_id="incident-workflow",
)
```

## Tool-Calling Example

```python
from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall


class DemoLLM:
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(
            content="The tool has been executed.",
            tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 3})],
        )


def add(a: int, b: int) -> str:
    return str(a + b)


agent = Agent(
    llm=DemoLLM(),
    prompt="You are a precise assistant.",
    tools=[FunctionTool.from_callable(add)],
)

result = agent.run("Add 2 and 3")
print(result.tool_results[0].output)
```

## Creating A New Tool

The simplest path is wrapping a normal Python callable:

```python
from shipit_agent import FunctionTool


def slugify(value: str) -> str:
    """Convert a title to a simple slug."""
    return value.lower().replace(" ", "-")


tool = FunctionTool.from_callable(
    slugify,
    name="slugify",
    description="Turn text into a URL-friendly slug.",
)
```

If you want full control over schema, output metadata, and prompt guidance, create a tool class:

```python
from shipit_agent.tools.base import ToolContext, ToolOutput


class WordCountTool:
    name = "count_words"
    description = "Count the number of words in a string."
    prompt = "Use this when the user needs deterministic word counts."
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

Then attach it to an agent:

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[WordCountTool()],
)
```

## Core Concepts

- `Agent`: public entrypoint
- `LLM`: protocol adapter for any model provider
- `Tool`: executable function with schema and structured output
- `MCPServer`: wrapper for MCP-backed tool collections
- `AgentProfileBuilder`: reusable builder for shipping presets

## Prebuilt Tools

```python
from shipit_agent import (
    Agent,
    AskUserTool,
    ArtifactBuilderTool,
    HumanReviewTool,
    GmailTool,
    MemoryTool,
    OpenURLTool,
    PlaywrightBrowserTool,
    PlannerTool,
    PromptTool,
    ToolSearchTool,
    VerifierTool,
    WebSearchTool,
    WorkspaceFilesTool,
)
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    prompt="You are a capable research agent.",
    tools=[
        WebSearchTool(),
        OpenURLTool(),
        PlaywrightBrowserTool(),
        AskUserTool(),
        HumanReviewTool(),
        MemoryTool(),
        PlannerTool(),
        PromptTool(),
        VerifierTool(),
        ToolSearchTool(),
        ArtifactBuilderTool(),
        WorkspaceFilesTool(),
        GmailTool(),
    ],
)
```

## Using Multiple Tools In One Agent

A practical pattern is to combine built-in tools with your own callable tools. The example script does exactly that: it wires `WebSearchTool`, `OpenURLTool`, `WorkspaceFilesTool`, `CodeExecutionTool`, and other built-ins together with local `FunctionTool` helpers like `project_context` and `add_numbers`.

```python
from shipit_agent import Agent, FunctionTool, get_builtin_tools
from shipit_agent.llms import BedrockChatLLM

llm = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
tools = get_builtin_tools(llm=llm, workspace_root=".shipit_workspace")
tools.append(FunctionTool.from_callable(add_numbers, name="add_numbers"))

agent = Agent(llm=llm, tools=tools)
```

You can mix deterministic tools, built-in tools, and file/code tools together:

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

That setup lets one agent:

- search the web
- run local computation
- save files
- use your own deterministic helper functions

## Web Search Provider Selection

`WebSearchTool` accepts either a provider object or a provider name. The default provider is `duckduckgo` so the library works without extra browser setup.

```python
from shipit_agent import WebSearchTool

default_search = WebSearchTool()
duckduckgo_search = WebSearchTool(provider="duckduckgo")
playwright_search = WebSearchTool(provider="playwright")
brave_search = WebSearchTool(provider="brave", api_key="BRAVE_API_KEY")
serper_search = WebSearchTool(provider="serper", api_key="SERPER_API_KEY")
tavily_search = WebSearchTool(provider="tavily", api_key="TAVILY_API_KEY")
```

You can also pass provider config:

```python
search = WebSearchTool(
    provider="duckduckgo",
    provider_config={"timeout": 20.0},
)
```

Use `playwright` only when JavaScript rendering matters:

```python
search = WebSearchTool(
    provider="playwright",
    provider_config={"timeout_ms": 20000},
)
```

## Default Agent Setup

`Agent` now ships with a default system prompt, retry policy, and router policy, so this works without extra setup:

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(llm=SimpleEchoLLM())
result = agent.run("Research the problem, plan the work, and save a report.")
```

You can override policies without replacing the whole prompt:

```python
from shipit_agent import Agent, RetryPolicy, RouterPolicy
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    retry_policy=RetryPolicy(max_llm_retries=2, max_tool_retries=1),
    router_policy=RouterPolicy(auto_plan=True, long_prompt_threshold=80),
)
```

## Code Execution

```python
from shipit_agent import CodeExecutionTool

tool = CodeExecutionTool()
result = tool.run(
    context=type("Ctx", (), {"state": {}})(),
    language="python",
    code="print('hello from shipit')",
)
```

Supported interpreter families include `python`, `bash`, `sh`, `zsh`, `javascript`, `typescript`, `ruby`, `php`, `perl`, `lua`, and `r`, subject to the interpreter being installed locally.

Example with file generation:

```python
from shipit_agent import Agent, CodeExecutionTool, WorkspaceFilesTool
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(
    llm=SimpleEchoLLM(),
    tools=[
        CodeExecutionTool(workspace_root=".shipit_workspace/code"),
        WorkspaceFilesTool(root_dir=".shipit_workspace"),
    ],
)
```

## MCP Discovery

```python
from shipit_agent import Agent, RemoteMCPServer, MCPHTTPTransport
from shipit_agent.llms import SimpleEchoLLM

mcp = RemoteMCPServer(
    name="docs",
    transport=MCPHTTPTransport("http://localhost:8080/mcp"),
)

agent = Agent.with_builtins(
    llm=SimpleEchoLLM(),
    mcps=[mcp],
)
```

You can also use subprocess transport for local MCP servers:

```python
from shipit_agent import PersistentMCPSubprocessTransport, RemoteMCPServer

mcp = RemoteMCPServer(
    name="local_docs",
    transport=PersistentMCPSubprocessTransport(["python", "my_mcp_server.py"]),
)
```

## Gmail And Third-Party Tools

`shipit_agent` now has a connector-style credential layer so tools like Gmail can be added cleanly instead of embedding credentials directly inside each tool.

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

This same pattern can be reused for:

- Google Calendar
- Google Drive
- Slack
- Linear
- Jira
- Notion
- Confluence
- custom internal APIs

## Using Tools And MCP Together

One agent can combine built-in tools, custom tools, and remote MCP capabilities at the same time:

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

That lets the runtime choose between:

- local tools
- remote MCP tools
- your own custom tools

## Streaming Events

Use `stream()` when you want step-by-step runtime events:

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent.with_builtins(llm=SimpleEchoLLM())

for event in agent.stream("Investigate this problem and use tools if needed."):
    print(event.type, event.message, event.payload)
```

Typical events include:

- `run_started`
- `planning_started`
- `planning_completed`
- `step_started`
- `tool_called`
- `tool_completed`
- `tool_retry`
- `llm_retry`
- `interactive_request`
- `run_completed`

## End-To-End Example

This is a more realistic setup for a project agent:

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

Tool layout:

- `shipit_agent/tools/open_url/open_url_tool.py`
- `shipit_agent/tools/web_search/providers.py`
- `shipit_agent/tools/web_search/web_search_tool.py`
- `shipit_agent/tools/ask_user/ask_user_tool.py`
- `shipit_agent/tools/human_review/human_review_tool.py`
- `shipit_agent/tools/prompt/prompt_tool.py`
- `shipit_agent/tools/verifier/verifier_tool.py`
- `shipit_agent/tools/sub_agent/sub_agent_tool.py`
- `shipit_agent/tools/tool_search/tool_search_tool.py`
- `shipit_agent/tools/artifact_builder/artifact_builder_tool.py`
- `shipit_agent/tools/code_execution/code_execution_tool.py`
- `shipit_agent/tools/playwright_browser/playwright_browser_tool.py`
- `shipit_agent/tools/memory/memory_tool.py`
- `shipit_agent/tools/planner/planner_tool.py`
- `shipit_agent/tools/workspace_files/workspace_files_tool.py`

## Model Adapters

- `shipit_agent.llms.OpenAIChatLLM`
- `shipit_agent.llms.AnthropicChatLLM`
- `shipit_agent.llms.LiteLLMChatLLM`
- `shipit_agent.llms.BedrockChatLLM`
- `shipit_agent.llms.GeminiChatLLM`
- `shipit_agent.llms.GroqChatLLM`
- `shipit_agent.llms.TogetherChatLLM`
- `shipit_agent.llms.OllamaChatLLM`

These adapters use optional dependencies and raise a clear error if the provider SDK is not installed.

Example:

```python
from shipit_agent import Agent
from shipit_agent.llms import BedrockChatLLM, GeminiChatLLM, LiteLLMChatLLM, OpenAIChatLLM

openai_agent = Agent(llm=OpenAIChatLLM(model="gpt-4o-mini"))
bedrock_agent = Agent(llm=BedrockChatLLM())
gemini_agent = Agent(llm=GeminiChatLLM())
generic_agent = Agent(llm=LiteLLMChatLLM(model="groq/llama-3.3-70b-versatile"))
```

## State

- `InMemoryMemoryStore`
- `InMemorySessionStore`

The runtime can persist messages across runs with `session_id` and store tool outputs as memory facts.

## Runtime Features

- default system prompt via `DEFAULT_AGENT_PROMPT`
- retry policy via `RetryPolicy`
- auto-planning router via `RouterPolicy`
- remote MCP discovery and transport adapters
- artifact export to files

## Status

This is a growing standalone agent runtime with built-in tools, remote MCP support, stronger runtime policies, and provider adapters.

---

<p align="center">
  <img src="shipit-icon.svg" alt="SHIPIT" width="40" height="40" />
  <br />
  <strong>Built with LOve. Powered by your choice of AI models.</strong>
  <br />
  <sub>Ship it fast. Ship it right.</sub>
</p>
