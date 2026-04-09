# Examples

Runnable examples for **shipit-agent**, ordered from simplest to most advanced. Each one is a self-contained Python file you can run directly with `python examples/<file>`.

## Setup (one-time)

```bash
# 1. Install shipit-agent + at least one provider SDK
pip install 'shipit-agent[openai]'
# or: pip install 'shipit-agent[all]'  for all providers

# 2. Copy the env template and fill in credentials
cp .env.example .env
# Edit .env — set SHIPIT_LLM_PROVIDER and at least one credential

# 3. Verify everything is wired up
python -c "from shipit_agent import Agent; print('OK')"
```

## The examples

| # | File | What it shows | Time | Best run with |
|---|---|---|---|---|
| **1** | [`01_hello_agent.py`](01_hello_agent.py) | The shortest possible runnable agent. One question, one answer. | ~10s | Any provider |
| **2** | [`02_streaming_with_reasoning.py`](02_streaming_with_reasoning.py) | Live streaming with colored event rendering. Shows reasoning blocks ("Thinking" panels) when the model surfaces them. | ~15s | `o3-mini`, `bedrock/openai.gpt-oss-120b-1:0`, `claude-opus-4-1` |
| **3** | [`03_provider_swap.py`](03_provider_swap.py) | Same agent, same prompt, run against 5 different providers back-to-back. Skips any provider whose credentials aren't configured. | ~30-60s | Multiple providers configured |
| **4** | [`04_research_agent.py`](04_research_agent.py) | End-to-end multi-step research workflow with `web_search` + `open_url` + grounded markdown report. Disables auto-planner and raises iteration cap. | ~30s | Any provider with web access |
| **5** | [`05_custom_tool.py`](05_custom_tool.py) | Build and attach two custom tools — one as a wrapped function, one as a full Tool class. Real domain logic (haversine distance + compound interest). | ~15s | Any provider |
| **6** | [`06_chat_session.py`](06_chat_session.py) | Persistent chat session with `FileSessionStore`. Remembers conversation across script restarts. Interactive REPL. | interactive | Any provider |
| **7** | [`07_tool_search.py`](07_tool_search.py) | Semantic tool discovery with `ToolSearchTool` — both standalone (no LLM) and in an actual agent loop. | ~15s | Any provider |

## Running

```bash
# From the repo root
python examples/01_hello_agent.py
python examples/02_streaming_with_reasoning.py
python examples/03_provider_swap.py
python examples/04_research_agent.py "What's the capital of New Zealand?"
python examples/05_custom_tool.py
python examples/06_chat_session.py
python examples/07_tool_search.py
```

Or use the `make` target:

```bash
make example   # runs examples/run_multi_tool_agent.py with the default prompt
```

## Override the provider per-run

The examples honor `SHIPIT_LLM_PROVIDER` from `.env` or the shell. You can override at the command line for one-off experiments:

```bash
# Test the same example against three providers
SHIPIT_LLM_PROVIDER=openai    python examples/02_streaming_with_reasoning.py
SHIPIT_LLM_PROVIDER=anthropic python examples/02_streaming_with_reasoning.py
SHIPIT_LLM_PROVIDER=bedrock   python examples/02_streaming_with_reasoning.py
```

## Templates (for reference, not direct runs)

These were the original template files — kept for backwards compatibility but the numbered examples above are the recommended starting point:

| File | Pattern |
|---|---|
| [`custom_function_tool_template.py`](custom_function_tool_template.py) | Old-style FunctionTool wrapper (use `05_custom_tool.py` instead) |
| [`custom_workspace_tool_template.py`](custom_workspace_tool_template.py) | Workspace-aware tool template |
| [`reasoning_agent_template.py`](reasoning_agent_template.py) | Reasoning-enabled agent template (use `02_streaming_with_reasoning.py` instead) |
| [`run_multi_tool_agent.py`](run_multi_tool_agent.py) | The big batteries-included example with `build_llm_from_env` and `build_demo_agent` — also imported by every numbered example |

## Choosing a provider for first run

If this is your first time, **`openai` with `gpt-4o-mini`** is the fastest path to a working example because:

- The OpenAI SDK is well-debugged
- `gpt-4o-mini` is cheap (~$0.15/M input tokens) so you can run all 7 examples for pennies
- API key setup is one env var: `OPENAI_API_KEY=sk-...`

If you want **reasoning blocks** ("Thinking" panels), use one of:

- `openai` with `SHIPIT_OPENAI_MODEL=o3-mini` (or `o1-mini` / `gpt-5`)
- `anthropic` with `claude-opus-4-1` and `thinking_budget_tokens=2048`
- `bedrock` with `bedrock/openai.gpt-oss-120b-1:0`

If you want **everything free**, use:

- `ollama` with `ollama/llama3.1` (requires local Ollama running on `http://localhost:11434`)

## Troubleshooting

| Symptom | Fix |
|---|---|
| `RuntimeError: Missing environment variable for X` | Set the credential in `.env` and re-run. The error tells you exactly which var. |
| `pip install` succeeds but `python examples/01_hello_agent.py` says `ModuleNotFoundError: shipit_agent` | You installed against a different Python interpreter. Try `python3.11 examples/...` |
| `make example` works but `python examples/01_hello_agent.py` doesn't | Run from the repo root, not the `examples/` directory. Add `PYTHONPATH=.` if needed. |
| Example uses tools but final answer is empty | Iteration cap hit. Edit the example and bump `agent.max_iterations = 8` |
| Bedrock errors with "toolResult blocks exceed toolUse" | Upgrade to `shipit-agent>=1.0.1` — this was fixed in the v1.0.1 release |
| `gpt-4o-mini` describes a plan instead of calling tools | It's lazy. Either use a stronger model, or add `tool_choice='required'` to the LLM constructor |

## Going deeper

Once you've worked through these examples, the [full documentation](https://shipiit.github.io/shipit_agent/) covers:

- [Streaming events reference](https://shipiit.github.io/shipit_agent/reference/events/) — all 14 event types with payloads
- [Architecture](https://shipiit.github.io/shipit_agent/reference/architecture/) — how the runtime loop works
- [Custom tools guide](https://shipiit.github.io/shipit_agent/guides/custom-tools/) — patterns for production tools
- [MCP integration](https://shipiit.github.io/shipit_agent/guides/mcp/) — attach remote MCP servers
- [Sessions and memory](https://shipiit.github.io/shipit_agent/guides/sessions/) — persistent state
