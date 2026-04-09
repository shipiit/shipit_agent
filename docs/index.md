---
title: SHIPIT Agent
description: A clean, powerful Python agent library with tools, MCP, streaming events, reasoning capture, and runtime policies.
hide:
  - navigation
---

# SHIPIT Agent

!!! tip "v1.0 is out"
    First stable release. Ships with **live reasoning events**, **truly incremental streaming**, **Bedrock tool-pairing guarantees**, **zero-friction provider switching**, and **in-process Playwright** for URL fetching. See the [changelog](changelog.md).

**SHIPIT Agent** is a standalone Python agent library focused on a clean runtime:

- bring your own LLM — or use any of seven built-in provider adapters
- attach Python tools, remote MCP servers, or connector-style third-party tools (Gmail, Drive, Slack, Linear, Notion, Jira, Confluence)
- iterate tool-using agents with configurable retry and router policies
- stream structured events (including **reasoning / thinking** blocks) as they happen
- inspect every step: reasoning, tool arguments, tool outputs, retries, final answer
- compose reusable agent profiles with system prompts and tool selections locked in
- keep clean boundaries between runtime, tools, MCP, policies, and profiles

Built for developers who want the agent loop **observable, interchangeable, and out of the way**.

---

## Install

```bash
pip install shipit-agent
```

With optional extras:

```bash
pip install 'shipit-agent[openai]'         # OpenAI SDK
pip install 'shipit-agent[anthropic]'      # Anthropic SDK (native thinking blocks)
pip install 'shipit-agent[litellm]'        # LiteLLM (Bedrock, Gemini, Groq, Together, …)
pip install 'shipit-agent[playwright]'     # In-process browser for open_url and web_search
pip install 'shipit-agent[all]'            # Everything
```

## 30-second example

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(llm=OpenAIChatLLM(model="gpt-4o-mini"))

for event in agent.stream("Search the web for today's Bitcoin price in USD."):
    print(event.type, event.message)
```

Emits events like:

```
run_started           Agent run started
step_started          LLM completion started
reasoning_started     🧠 Model reasoning started
reasoning_completed   🧠 Model reasoning completed
tool_called           Tool called: web_search
tool_completed        Tool completed: web_search
run_completed         Agent run completed
```

---

## Why SHIPIT Agent

<div class="grid cards" markdown>

-   :material-brain: **Live reasoning events**

    ---

    Extended thinking blocks from o1/o3/gpt-5/Claude/gpt-oss are automatically extracted and streamed as `reasoning_started` / `reasoning_completed` events. Your UI can show a live "Thinking" panel for free.

    [:octicons-arrow-right-24: Reasoning guide](guides/reasoning.md)

-   :material-lightning-bolt: **Truly incremental streaming**

    ---

    `agent.stream()` runs the agent on a background thread and yields events through a queue as they happen. Works in Jupyter, VS Code, WebSocket, SSE, and terminals.

    [:octicons-arrow-right-24: Streaming guide](guides/streaming.md)

-   :material-shield-check: **Bulletproof Bedrock tool pairing**

    ---

    Every `toolUse` gets a paired `toolResult`. Planner output is injected as user context, not orphan tool-results. Hallucinated tool names get synthetic error results. Multi-iteration Bedrock loops just work.

    [:octicons-arrow-right-24: Architecture](reference/architecture.md)

-   :material-magnify-scan: **Semantic tool discovery**

    ---

    `tool_search` lets the agent ask "which tool should I use for X?" and get a ranked shortlist. No more 28-tool context bloat, no more tool hallucinations.

    [:octicons-arrow-right-24: Tool search guide](guides/tool-search.md)

-   :material-key-variant: **Zero-friction provider switching**

    ---

    Edit one line in `.env` — `SHIPIT_LLM_PROVIDER=openai` — and `build_llm_from_env()` does the rest. Seven providers supported out of the box.

    [:octicons-arrow-right-24: Environment setup](getting-started/environment.md)

-   :material-web: **Playwright-powered `open_url`**

    ---

    In-process Chromium fetches JS-rendered pages with a realistic UA, handles anti-bot 503s, and falls back to stdlib urllib if Playwright isn't installed. No external scraper services.

    [:octicons-arrow-right-24: Prebuilt tools](guides/prebuilt-tools.md)

</div>

---

## Next steps

- [**Install and run the quick start**](getting-started/quickstart.md) — get an agent running in five minutes
- [**Explore streaming events**](guides/streaming.md) — understand the 14 event types and what they carry
- [**Reasoning and thinking steps**](guides/reasoning.md) — render a live "Thinking" panel in your UI
- [**Create a custom tool**](guides/custom-tools.md) — build a new tool from scratch
- [**MCP integration**](guides/mcp.md) — attach remote MCP servers to extend capabilities
