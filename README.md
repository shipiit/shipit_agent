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
  <a href="https://docs.shipiit.com/"><strong>📖 Documentation</strong></a> ·
  <a href="https://pypi.org/project/shipit-agent/"><strong>📦 PyPI</strong></a> ·
  <a href="https://docs.shipiit.com/getting-started/quickstart/">Quick start</a> ·
  <a href="https://docs.shipiit.com/guides/streaming/">Streaming</a> ·
  <a href="https://docs.shipiit.com/guides/reasoning/">Reasoning</a> ·
  <a href="https://docs.shipiit.com/guides/tool-search/">Tool search</a> ·
  <a href="SECURITY.md">Security</a>
</p>

<p align="center">
  <em>Readable docs, explicit tools, and a runtime that is small enough to extend without fighting framework overhead.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/shipit-agent/"><img src="https://img.shields.io/pypi/v/shipit-agent?style=for-the-badge&color=blue&label=pypi" alt="PyPI" /></a>
  <a href="https://pypi.org/project/shipit-agent/"><img src="https://img.shields.io/pypi/pyversions/shipit-agent?style=for-the-badge&color=green" alt="Python versions" /></a>
  <a href="https://pypi.org/project/shipit-agent/"><img src="https://img.shields.io/pypi/dm/shipit-agent?style=for-the-badge&color=purple&label=downloads" alt="Downloads" /></a>
  <a href="LICENSE.md"><img src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge" alt="License" /></a>
  <a href="https://docs.shipiit.com/"><img src="https://img.shields.io/badge/docs-mkdocs--material-483D8B?style=for-the-badge" alt="Docs" /></a>
</p>

<p align="center">
  <strong>Install</strong> &nbsp;·&nbsp; <code>pip install shipit-agent</code>
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

## 🚀 What's new in 1.0.3

**SHIPIT Agent 1.0.3** ships **Super RAG**, the **DeepAgent factory**, a **live multi-agent chat REPL**, and an **Agent memory cookbook**. **521 unit tests. 19 Bedrock end-to-end smoke tests. All passing.**

### Super RAG — hybrid search with auto-cited sources

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/manual.pdf")

agent = Agent.with_builtins(llm=llm, rag=rag)
result = agent.run("How do I configure logging?")

print(result.output)              # "Set SHIPIT_LOG_LEVEL=debug. [1]"
for src in result.rag_sources:     # DRK_CACHE-style citation panel
    print(f"[{src.index}] {src.source}: {src.text[:80]}")
```

Pluggable `VectorStore` / `KeywordStore` / `Embedder` / `Reranker` protocols, hybrid vector+BM25 search with Reciprocal Rank Fusion, context expansion, optional recency bias, and a thread-local per-run source tracker.

### DeepAgent — one factory, all the power

```python
from shipit_agent.deep import DeepAgent, Goal

agent = DeepAgent.with_builtins(
    llm=llm,
    rag=rag,                                 # grounded answers
    verify=True,                              # verifier after every answer
    reflect=True,                             # self-critique loop
    goal=Goal(                                # goal-driven decomposition
        objective="Ship the auth fix",
        success_criteria=["Patch compiles", "Tests pass"],
    ),
    agents=[researcher, writer, reviewer],    # named sub-agent delegates
)
result = agent.run()
```

Seven deep tools wired automatically (`plan_task`, `decompose_problem`, `workspace_files`, `sub_agent`, `synthesize_evidence`, `decision_matrix`, `verify_output`). `create_deep_agent()` gives you the functional spelling and auto-wraps plain Python functions as tools.

### Live chat — `shipit chat`

```bash
shipit chat                                    # default: DeepAgent
shipit chat --agent goal --goal "Build a CLI"
shipit chat --rag-file docs/manual.pdf --reflect --verify
```

Modern multi-agent terminal REPL. Switch agent types live with `/agent`, index files mid-session with `/index`, save/load conversations, toggle `reflect`/`verify`, inspect sources. Works with every LLM provider.

### Agent memory — OpenAI-style "remember things"

```python
from shipit_agent import Agent, AgentMemory
from shipit_agent.stores import FileMemoryStore, FileSessionStore

profile = AgentMemory.default(llm=llm, embedding_fn=embed)
profile.add_fact("user_timezone=Europe/Berlin")

agent = Agent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),      # LLM-writable
    session_store=FileSessionStore(root="~/.shipit/sessions"),  # chat history
    history=profile.get_conversation_messages(),                # curated profile
)
```

Two complementary memory systems: `memory_store=` for the LLM's `memory` tool, `AgentMemory` for application-curated profiles. Full cookbook in `docs/agent/memory.md`.

---

## 🎯 Also new in 1.0.3

**SHIPIT Agent 1.0.2** (still available) introduced deep agents, structured output, pipelines, agent teams, advanced memory, and output parsers. 1.0.3 builds directly on that foundation.

### Deep Agents — Beyond LangChain

```python
from shipit_agent.deep import GoalAgent, Goal, ReflectiveAgent, Supervisor, Worker

# GoalAgent — autonomous goal decomposition with streaming
agent = GoalAgent.with_builtins(llm=llm, goal=Goal(
    objective="Build a comparison of Python web frameworks",
    success_criteria=["Covers Django, Flask, FastAPI", "Includes benchmarks"],
))
for event in agent.stream():
    print(f"[{event.type}] {event.message}")
    if event.payload.get("output"):
        print(event.payload["output"][:200])

# ReflectiveAgent — self-improving with quality scores
agent = ReflectiveAgent.with_builtins(llm=llm, quality_threshold=0.8)
result = agent.run("Explain the CAP theorem")
print(f"Quality: {result.final_quality}, Revisions: {len(result.revisions)}")

# Supervisor — hierarchical multi-agent management
supervisor = Supervisor.with_builtins(llm=llm, worker_configs=[
    {"name": "analyst", "prompt": "You analyze data."},
    {"name": "writer", "prompt": "You write reports."},
])
for event in supervisor.stream("Analyze AI trends and write a summary"):
    print(f"[{event.payload.get('worker', 'supervisor')}] {event.message}")
```

### Structured Output — One Parameter

```python
from pydantic import BaseModel

class Analysis(BaseModel):
    sentiment: str
    confidence: float
    topics: list[str]

result = agent.run("Analyze this review", output_schema=Analysis)
result.parsed.sentiment   # "positive"
result.parsed.confidence  # 0.95
```

### Pipeline Composition

```python
from shipit_agent import Pipeline, step, parallel

pipe = Pipeline(
    parallel(
        step("research", agent=researcher, prompt="Research {topic}"),
        step("trends", agent=analyst, prompt="Trends in {topic}"),
    ),
    step("write", agent=writer, prompt="Article using:\n{research.output}\n{trends.output}"),
)
for event in pipe.stream(topic="AI agents"):
    print(f"[{event.payload.get('step', '')}] {event.message}")
```

### Agent Teams + Channels + Memory + Benchmark

```python
# Agent team with LLM-routed coordination
team = AgentTeam(coordinator=llm, agents=[researcher, writer, reviewer])
for event in team.stream("Write a guide about async Python"):
    print(f"[{event.payload.get('agent')}] {event.message}")

# Typed agent communication
channel = Channel(name="pipeline")
channel.send(AgentMessage(from_agent="a", to_agent="b", type="data", data={...}))

# Advanced memory (conversation + semantic + entity)
memory = AgentMemory.default(llm=llm, embedding_fn=my_embed)

# Systematic agent testing
report = AgentBenchmark(name="eval", cases=[
    TestCase(input="What is Docker?", expected_contains=["container"]),
]).run(agent)
print(report.summary())
```

### Also in 1.0.2

- **Parallel tool execution** — `parallel_tool_execution=True`
- **Graceful tool failure** — errors become messages, not crashes
- **Context window management** — token tracking + auto-compaction
- **Hooks & middleware** — `@hooks.on_before_llm`, `@hooks.on_after_tool`
- **Async runtime** — `AsyncAgentRuntime` for FastAPI
- **Mid-run re-planning** — `replan_interval=N`
- **Transient error auto-retry** — 429/500/503 retried automatically
- **Output parsers** — JSON, Pydantic, Regex, Markdown

---

## 🚀 What's new in 1.0

**SHIPIT Agent 1.0** is the first stable release. It ships a production-ready agent runtime built around three ideas: **every step is observable**, **every provider is interchangeable**, and **the runtime stays out of your way**. The headline features:

- **🧠 Live reasoning / "thinking" events.** When the underlying model surfaces a reasoning block — OpenAI o-series (`o1`, `o3`, `o4`), `gpt-5`, DeepSeek R1, Anthropic Claude extended thinking, or AWS Bedrock `openai.gpt-oss-120b` — the runtime extracts it and emits `reasoning_started` / `reasoning_completed` events **before** the corresponding `tool_called` events. Your UI can render a live "Thinking" panel that matches what the model is actually doing under the hood, with no manual wiring. All three LLM adapters (direct OpenAI, direct Anthropic, LiteLLM/Bedrock) now share a common `reasoning_content` extraction helper that handles flat `reasoning_content` attributes, Anthropic-style `thinking_blocks`, and pydantic `model_dump()` fallbacks.
- **⚡ Truly incremental streaming.** `agent.stream()` now runs the agent on a background worker thread and yields `AgentEvent` objects through a thread-safe queue as they are emitted by the runtime. No more "everything arrives at once at the end" — each `run_started`, `reasoning_completed`, `tool_called`, `tool_completed` event reaches your loop the instant it happens. Works in Jupyter, VS Code, JupyterLab, WebSocket/SSE packet transports, and plain terminals. Errors in the background worker are captured and re-raised on the consumer thread so nothing gets silently swallowed.
- **🛡️ Bulletproof Bedrock tool pairing.** AWS Bedrock's Converse API enforces strict 1:1 pairing between `toolUse` blocks in an assistant turn and `toolResult` blocks in the next user turn. The 1.0 runtime guarantees this invariant everywhere: the planner output is injected as a `user`-role context message rather than an orphan `toolResult`; every `response.tool_calls` entry gets **either** a real tool-result **or** a synthetic error tool-result (for hallucinated tool names) so pairing never drifts; each call is stamped with a stable `call_{iteration}_{index}` ID that round-trips through the message metadata. Multi-iteration tool loops on Bedrock Claude, Bedrock gpt-oss, and Anthropic native all work reliably without `modify_params` band-aids.
- **🔑 Zero-friction provider switching via `.env`.** `build_llm_from_env()` now walks upward from CWD to discover a `.env` file, so the same notebook or script works whether CWD is the repo root, a `notebooks/` subdirectory, or a deeply nested workspace. Switching providers is a one-line `.env` edit (`SHIPIT_LLM_PROVIDER=openai|anthropic|bedrock|gemini|vertex|litellm|groq|together|ollama`) — no kernel restarts, no code edits, no custom boot scripts. Providers are supported out of the box with credential validation that raises a helpful error pointing to the exact env var you forgot to set.
- **🌐 In-process Playwright for `open_url`.** The built-in `open_url` tool now uses Playwright's Chromium directly (headless, realistic desktop UA, 1280×800 viewport, `en-US` locale) as its primary fetch path. Handles JS-rendered pages, anti-bot protections, and modern TLS/ALPN without depending on any external scraper service. Stdlib `urllib` is kept as a zero-dep fallback for static pages and environments without Playwright installed. No third-party HTTP libraries (no `httpx`, no `requests`, no `beautifulsoup4`) — just Playwright and the standard library. Errors never raise out of the tool: they come back as a normal `ToolOutput` with a `warnings` list in metadata, so the runtime's tool pairing stays balanced even when a target URL is down.
- **🪵 Full event table for observability.** 14 distinct event types are emitted over the lifetime of a run: `run_started`, `mcp_attached`, `planning_started`, `planning_completed`, `step_started`, `reasoning_started`, `reasoning_completed`, `tool_called`, `tool_completed`, `tool_retry`, `tool_failed`, `llm_retry`, `interactive_request`, `run_completed` — each with a documented payload and a stable shape. The [Streaming Events](#streaming-events) section below has a complete reference and a 17-step example trace of a real Bedrock run.
- **🔁 Iteration-cap summarization fallback.** If the model is still calling tools when the loop hits `max_iterations`, the runtime automatically gives it one more turn with `tools=[]` to force a natural-language summary, so consumers never see an empty final answer. The fallback is guarded with try/except so a summarization failure can't mask the rest of the run.
- **🧩 Clean separation of concerns.** Runtime, tool registry, LLM adapters, MCP integration, memory, sessions, tracing, retry/router policies, and agent profiles are each one small module with a well-defined boundary. If you want to bring your own tool, your own LLM, your own MCP transport, or your own session store, you implement a single protocol and plug it in — no framework ceremony, no metaclasses, no hidden globals.

### Core feature summary

- bring your own LLM, or use any of the seven built-in provider adapters
- attach Python tools as classes, as `FunctionTool` wrappers, or as connector-style third-party tools (Gmail, Google Drive, Slack, …)
- attach local and remote MCP servers — HTTP, stdio subprocess, and persistent sessions all supported
- use prebuilt tools like `web_search`, `open_url` (Playwright-backed), `ask_user`, `human_review`, `code_interpreter`, `file_editor`, and more
- iterative multi-step tool loops with configurable `max_iterations` and an automatic summarization fallback
- built-in retry policies for transient LLM and tool errors, with dedicated `llm_retry` / `tool_retry` events
- memory store (in-memory or file-backed) for cross-turn facts, session store for conversation resumption, trace store for audit logs
- support for **OpenAI, Anthropic, AWS Bedrock, Google Gemini, Groq, Together AI, Ollama, Vertex AI, OpenRouter**, and any other LiteLLM-backed provider
- stream structured events through `agent.stream()`, `chat_session.stream_packets(transport="websocket")`, or `chat_session.stream_packets(transport="sse")`
- inspect every step: reasoning, tool arguments, tool outputs, retries, iteration counts, final answer
- compose reusable agent profiles with system prompts, tool selections, and policies locked in
- ship with a strong default system prompt and router/retry policies that work out of the box
- persistent file-backed session and memory stores for long-running, resumable agents
- persistent MCP subprocess sessions with graceful shutdown on run completion

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

- 🌐 **[Full documentation site](https://docs.shipiit.com/)** — MkDocs Material, searchable, versioned
    - [Quick start](https://docs.shipiit.com/getting-started/quickstart/) · [Installation](https://docs.shipiit.com/getting-started/install/) · [Environment setup](https://docs.shipiit.com/getting-started/environment/)
    - [Streaming events](https://docs.shipiit.com/guides/streaming/) · [Reasoning & thinking](https://docs.shipiit.com/guides/reasoning/) · [Tool search](https://docs.shipiit.com/guides/tool-search/)
    - [Custom tools](https://docs.shipiit.com/guides/custom-tools/) · [MCP integration](https://docs.shipiit.com/guides/mcp/) · [Sessions & memory](https://docs.shipiit.com/guides/sessions/)
    - [Architecture](https://docs.shipiit.com/reference/architecture/) · [Event types reference](https://docs.shipiit.com/reference/events/) · [Model adapters](https://docs.shipiit.com/reference/adapters/)
- [Changelog](https://docs.shipiit.com/changelog/) — full v1.0 release notes
- [docs.md](docs.md) — legacy flat-markdown docs (kept for offline browsing)
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

For Vertex AI with a service-account JSON file:

```env
SHIPIT_LLM_PROVIDER=vertex
SHIPIT_VERTEX_MODEL=vertex_ai/gemini-1.5-pro
SHIPIT_VERTEX_CREDENTIALS_FILE=/absolute/path/to/vertex-service-account.json
VERTEXAI_PROJECT=your-gcp-project-id
VERTEXAI_LOCATION=us-central1
```

This automatically maps `SHIPIT_VERTEX_CREDENTIALS_FILE` to `GOOGLE_APPLICATION_CREDENTIALS` for LiteLLM/Vertex usage.

For a generic LiteLLM proxy or server:

```env
SHIPIT_LLM_PROVIDER=litellm
SHIPIT_LITELLM_MODEL=openrouter/openai/gpt-4o-mini
SHIPIT_LITELLM_API_BASE=http://localhost:4000
SHIPIT_LITELLM_API_KEY=your-litellm-key
```

If your LiteLLM route needs a custom provider hint, also set:

```env
SHIPIT_LITELLM_CUSTOM_PROVIDER=openrouter
```

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

### `tool_search` — let the agent discover its own tools

When an agent has more than a handful of tools, two problems appear:

1. **Token bloat** — every turn ships the full tool catalog to the LLM.
2. **Tool hallucination** — similar tool names get confused and the model invents ones that don't exist.

`ToolSearchTool` solves both. Give the model a plain-language query and it returns a **ranked shortlist** of the best-matching tools currently registered on the agent, with names, descriptions, usage hints, and relevance scores:

```python
from shipit_agent import Agent, ToolSearchTool
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(llm=OpenAIChatLLM(model="gpt-4o-mini"))
# ToolSearchTool is included in Agent.with_builtins automatically.

result = agent.run(
    "Use tool_search to find the right tool for fetching a specific URL, "
    "then call that tool on https://example.com"
)
```

The model will first call `tool_search({"query": "fetch a specific URL", "limit": 3})` and receive something like:

```
Best tools for 'fetch a specific URL' (ranked by relevance):
1. open_url (score=0.4217) — Fetch a URL and return a clean text excerpt.
   ↳ when to use: Use this when you need exact content from a specific URL…
2. playwright_browser (score=0.3104) — Drive a headless browser…
   ↳ when to use: Use for pages requiring interaction or anti-bot protection.
3. web_search (score=0.1875) — Search the web with a configurable provider…
   ↳ when to use: Use when you need fresh information from the internet.
```

Then call `open_url` directly with the right arguments. No hallucinations, no wasted tokens on 27 irrelevant schemas.

**Scoring algorithm** (pure stdlib, no embeddings, no external API):

```
score = SequenceMatcher(query, haystack).ratio() + 0.12 × token_hits
```

where `haystack` concatenates each tool's `name`, `description`, and `prompt_instructions`, and `token_hits` counts how many query words appear literally. Tie-broken by insertion order. Results below `score=0.05` are filtered as noise.

**Configurable knobs:** `max_limit` (hard cap, default 10), `default_limit` (default 5), `token_bonus` (default 0.12). Override at construction time:

```python
ToolSearchTool(max_limit=15, default_limit=8, token_bonus=0.20)
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

| Event type | When it fires | Key payload fields |
|---|---|---|
| `run_started` | Very first event of a run, once per `stream()`/`run()` call. | `prompt` |
| `mcp_attached` | Once per attached MCP server, right after `run_started`. | `server` |
| `planning_started` | The router policy decided the prompt is complex enough to invoke the `plan_task` tool. Fires **before** the first LLM call. | `prompt` |
| `planning_completed` | Planner returned. The plan is injected into the message history as a `user`-role context message so Bedrock tool pairing stays intact. | `output` |
| `step_started` | Each iteration of the tool loop, right before calling the LLM. | `iteration`, `tool_count` |
| `reasoning_started` | 🧠 The LLM response contained a thinking/reasoning block (OpenAI o-series, `gpt-oss`, Claude extended thinking, DeepSeek R1…). Fires **once per iteration** when reasoning is present. | `iteration` |
| `reasoning_completed` | Immediately after `reasoning_started`, carrying the full reasoning text. Use this to render a "Thinking" panel in your UI. | `iteration`, `content` |
| `tool_called` | The model decided to call a tool. Fires before execution. | `iteration`, `arguments` (`ev.message` is `"Tool called: <name>"`) |
| `tool_completed` | Tool finished successfully. | `iteration`, `output` |
| `tool_retry` | Transient tool failure, retry scheduled by `RetryPolicy`. | `iteration`, `attempt`, `error` |
| `tool_failed` | Tool raised a non-retryable error, **or** the model hallucinated a tool name that isn't registered. In the second case a synthetic error tool-result is still appended so tool_use/tool_result pairing stays balanced (required by Bedrock Converse). | `iteration`, `error` |
| `llm_retry` | Transient LLM provider error, retry scheduled. | `attempt`, `error` |
| `interactive_request` | A tool returned `metadata.interactive=True` (e.g. `ask_user`, human review). UI can pause and collect input. | `kind`, `payload` |
| `run_completed` | Final event, emitted once no more tool calls are requested. | `output` |

### Reasoning / "thinking" steps

When the underlying model surfaces reasoning content (OpenAI o-series via `reasoning_effort`, Anthropic Claude via extended thinking, AWS Bedrock `openai.gpt-oss-120b` via native reasoning, DeepSeek R1, etc.) the runtime automatically extracts it from the provider response and emits a `reasoning_started` + `reasoning_completed` pair before any subsequent `tool_called` events. The LiteLLM adapter handles three shapes:

1. **Flat `reasoning_content`** on the response message (OpenAI / gpt-oss / DeepSeek via LiteLLM).
2. **Anthropic `thinking_blocks[*].thinking`** (Claude extended thinking).
3. **`model_dump()` fallback** — any `reasoning_content` / `thinking_blocks` key found in the pydantic dump.

No extra configuration is needed — `LLMResponse.reasoning_content` is populated automatically, and the runtime emits the events whenever it's non-empty. Models that don't expose reasoning simply won't produce these events; no error, no warning.

A typical Bedrock `gpt-oss-120b` run with two tool calls produces:

```
1.  run_started        → "Agent run started"
2.  planning_started   → "Planner started"
3.  planning_completed → "Planner completed"
4.  step_started       → iteration=1, tool_count=28
5.  reasoning_started  → 🧠 iteration=1
6.  reasoning_completed→ 🧠 "The user wants two independent live BTC prices. I'll start with web_search..."
7.  tool_called        → "Tool called: web_search"
8.  tool_completed     → "Tool completed: web_search"
9.  step_started       → iteration=2
10. reasoning_completed→ 🧠 "Now I'll open both URLs to confirm..."
11. tool_called        → "Tool called: open_url"
12. tool_completed     → "Tool completed: open_url"
13. tool_called        → "Tool called: open_url"
14. tool_completed     → "Tool completed: open_url"
15. step_started       → iteration=3
16. reasoning_completed→ 🧠 "Both sources agree within $40..."
17. run_completed      → final markdown report
```

Because `stream()` runs the agent on a background thread and pushes events through a queue, every event is yielded **as it happens** — your UI can render the thinking block, then the tool calls, then the final answer incrementally (see `notebooks/04_agent_streaming_packets.ipynb` for a live example).

### Tool lifecycle & Bedrock tool pairing

AWS Bedrock's Converse API enforces strict 1:1 pairing between `toolUse` blocks in an assistant turn and `toolResult` blocks in the next user turn. The runtime guarantees this invariant:

- Every `response.tool_calls` entry gets **either** a successful tool-result message **or** a synthetic error tool-result (for hallucinated/unregistered tool names) — never a dropped orphan.
- The planner output is injected as a regular `user`-role context message rather than a `tool`-role message, so it never appears as an unpaired `toolResult`.
- Each tool call is stamped with a stable `call_{iteration}_{index}` ID that round-trips through `Message.metadata.tool_calls[i].id` ↔ `Message.metadata.tool_call_id` on the result.

This means multi-iteration tool loops work reliably on Bedrock Claude, Bedrock gpt-oss, and Anthropic native — no `modify_params` band-aids required.

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
from shipit_agent.llms import BedrockChatLLM, GeminiChatLLM, LiteLLMChatLLM, OpenAIChatLLM, VertexAIChatLLM

openai_agent = Agent(llm=OpenAIChatLLM(model="gpt-4o-mini"))
bedrock_agent = Agent(llm=BedrockChatLLM())
gemini_agent = Agent(llm=GeminiChatLLM())
vertex_agent = Agent(llm=VertexAIChatLLM(model="vertex_ai/gemini-1.5-pro"))
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
