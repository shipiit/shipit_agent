# Quick Start

Get a working agent with tools, streaming, and reasoning in five minutes.

## 1. Install

```bash
pip install 'shipit-agent[openai]'
```

## 2. Set your API key

Create `.env` in your project root:

```bash
SHIPIT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
SHIPIT_OPENAI_MODEL=gpt-4o-mini
```

## 3. Run your first agent

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env()            # reads SHIPIT_LLM_PROVIDER from .env
agent = Agent.with_builtins(llm=llm)  # includes web_search, open_url, tool_search, …

result = agent.run("Find today's Bitcoin price in USD from a reputable source.")
print(result.output)
```

## 4. Stream events instead

Replace `agent.run(...)` with `agent.stream(...)` to watch each step happen live:

```python
for event in agent.stream("Find today's Bitcoin price in USD."):
    print(f"{event.type:20s} {event.message}")
```

You'll see:

```
run_started          Agent run started
step_started         LLM completion started
reasoning_started    🧠 Model reasoning started
reasoning_completed  🧠 Model reasoning completed
tool_called          Tool called: web_search
tool_completed       Tool completed: web_search
step_started         LLM completion started
tool_called          Tool called: open_url
tool_completed       Tool completed: open_url
run_completed        Agent run completed
```

Every event is yielded **the instant it happens**, not buffered until the end. Your UI can render a live "Thinking" panel, a tool call log, and a final answer — all incrementally.

## 5. Switch providers

Change one line in `.env`:

```bash
SHIPIT_LLM_PROVIDER=bedrock          # or anthropic, gemini, groq, together, ollama
```

Restart, re-run. **No code change.** Credentials are loaded from whichever env vars the provider needs (`AWS_REGION_NAME`, `ANTHROPIC_API_KEY`, etc.) — `build_llm_from_env` raises a clear error if any are missing.

## Next

- [Streaming guide](../guides/streaming.md) — understand all 14 event types
- [Reasoning & thinking](../guides/reasoning.md) — render thinking panels from model reasoning blocks
- [Tool search](../guides/tool-search.md) — let the agent discover its own tools
- [Custom tools](../guides/custom-tools.md) — build a new tool from scratch
