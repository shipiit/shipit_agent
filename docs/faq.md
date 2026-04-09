---
title: FAQ
description: Frequently asked questions about shipit-agent — installation, providers, tools, streaming, troubleshooting, and production deployment.
---

# Frequently Asked Questions

## General

### What is shipit-agent for?

Building production agents with tools, MCP servers, streaming reasoning events, and clean provider switching. It's a **library**, not a framework — the runtime is small (~400 lines), every component is pluggable, and there's no hidden ceremony. Bring your own LLM, your own tools, your own storage; the runtime composes them.

### How is it different from LangChain / LangGraph / CrewAI?

- **Smaller surface area** — `shipit_agent/runtime.py` is one file you can read in a sitting
- **No abstraction tax** — no chains, no graphs, no mandatory inheritance hierarchies
- **Reasoning events as first-class citizens** — automatic extraction from any provider
- **Bedrock tool-pairing guarantees** — multi-iteration loops on AWS Bedrock just work
- **Truly incremental streaming** — events arrive the instant they're emitted, not buffered until completion
- **Zero mandatory deps** — every LLM SDK is an optional extra

We aren't trying to replace those libraries. If you need a complex DAG of agents with cycles and state machines, LangGraph is great. If you need a multi-agent role-playing simulation, CrewAI is great. shipit-agent is for the case where you want a clean, observable, single-agent runtime that does exactly what you tell it.

### Is it production-ready?

v1.0.1 is the current stable release. Used in production for research agents, customer support bots, and code-review workflows. 92 tests, full CI, gitleaks secret scanning, MIT licensed.

If you find a bug, [open an issue](https://github.com/shipiit/shipit_agent/issues/new?template=bug_report.yml).

### What's the license?

MIT. Use it however you like.

---

## Installation

### Which extras should I install?

| Use case | Install |
|---|---|
| Just trying it out with OpenAI | `pip install 'shipit-agent[openai]'` |
| Using AWS Bedrock | `pip install 'shipit-agent[litellm]'` |
| Using Claude directly | `pip install 'shipit-agent[anthropic]'` |
| Need browser-based URL fetching | `pip install 'shipit-agent[playwright]'` |
| Want everything | `pip install 'shipit-agent[all]'` |

### `pip install` works but `python -c "import shipit_agent"` says ModuleNotFoundError

You probably installed against a different Python interpreter than the one you're running. Try:

```bash
which python python3 python3.11
python3.11 -m pip install shipit-agent
python3.11 -c "import shipit_agent; print(shipit_agent.__version__)"
```

### Can I use it with Python 3.10?

No. shipit-agent requires Python 3.11+. The runtime uses several 3.11-only features (`StrEnum`, improved `tomllib`, `Self` type, structural pattern matching enhancements). Upgrading to 3.11 is the only fix.

---

## Providers

### Which provider should I start with?

**`openai` with `gpt-4o-mini`** if you have an OpenAI API key — cheapest, fastest, most reliable.

**`bedrock` with `openai.gpt-oss-120b-1:0`** if you have AWS credentials — cheapest reasoning-capable model.

**`ollama` with `llama3.1`** if you want everything local and free.

### How do I switch providers?

One line in `.env`:

```bash
SHIPIT_LLM_PROVIDER=openai      # or anthropic, bedrock, gemini, vertex, groq, together, ollama, litellm
```

No code change needed. `build_llm_from_env()` reads this var and constructs the right adapter automatically.

### Why does my agent run with reasoning events on one provider but not another?

Because **reasoning content is provider-specific**. Models that surface reasoning blocks (OpenAI o-series, Claude with extended thinking, Bedrock gpt-oss, DeepSeek R1) emit them; models that don't (gpt-4o, gpt-4o-mini, Llama 3, Gemini 1.5) won't. shipit-agent extracts whatever the model actually returns — there's no way to add reasoning to a model that doesn't produce it.

See the [reasoning guide](guides/reasoning.md#which-models-produce-reasoning) for the full compatibility matrix.

### How do I use my own LiteLLM proxy server?

Set these in `.env`:

```bash
SHIPIT_LLM_PROVIDER=litellm
SHIPIT_LITELLM_MODEL=gpt-4o-mini          # whatever model the proxy routes to
SHIPIT_LITELLM_API_BASE=https://litellm.my-company.internal
SHIPIT_LITELLM_API_KEY=sk-proxy-token
```

`build_llm_from_env()` auto-detects proxy mode when `SHIPIT_LITELLM_API_BASE` is set and uses `LiteLLMProxyChatLLM` instead of direct LiteLLM SDK mode.

### Vertex AI service-account file?

Set up via `SHIPIT_VERTEX_CREDENTIALS_FILE`:

```bash
SHIPIT_LLM_PROVIDER=vertex
SHIPIT_VERTEX_CREDENTIALS_FILE=/path/to/sa.json
VERTEXAI_PROJECT=my-gcp-project
VERTEXAI_LOCATION=us-central1
```

The adapter sets `GOOGLE_APPLICATION_CREDENTIALS` automatically so `google-auth` picks it up.

---

## Tools

### My agent has 28 tools and uses too many tokens per turn. What do I do?

Add `tool_search` to the registry and instruct the model to use it first:

```python
prompt = (
    "Before calling any other tool, first call `tool_search` to confirm "
    "which tool fits. Then proceed."
)
```

The model will get a ranked shortlist of 5 relevant tools instead of seeing all 28. See the [tool search guide](guides/tool-search.md).

### How do I write a custom tool?

Three things: `name`, `schema()`, `run(context, **kwargs)`. See [custom tools guide](guides/custom-tools.md) and the worked example in [`examples/05_custom_tool.py`](https://github.com/shipiit/shipit_agent/blob/main/examples/05_custom_tool.py).

### Why does my tool's `run()` get `TypeError: got multiple values for argument 'context'`?

You hit the v1.0.0 bug. **Upgrade to v1.0.1+** — `pip install -U shipit-agent` — and the runtime now strips `context` and `self` from tool-call arguments before forwarding so there's no collision.

### Can my tool be async?

Tool `run()` is sync because the runtime treats every tool call as atomic. If your tool needs async work internally (e.g. concurrent HTTP requests), wrap it with `asyncio.run()`:

```python
def run(self, context, **kwargs):
    import asyncio
    result = asyncio.run(self._async_work(**kwargs))
    return ToolOutput(text=result, metadata={...})
```

For long-running async I/O, consider running the tool work in a thread pool to avoid blocking the runtime's background thread.

### How do I disable the planner?

```python
from shipit_agent.policies import RouterPolicy

agent.router_policy = RouterPolicy(auto_plan=False)
```

The `plan_task` tool stays available in the registry — the model can still call it explicitly — but the runtime won't auto-invoke it before the first LLM call.

---

## Streaming

### `agent.stream()` returns all events at once at the end. Why isn't it streaming?

This was a real bug in pre-1.0 versions. **Upgrade to v1.0.1+** — `agent.stream()` now uses a background thread with a `queue.Queue` so events are yielded the instant they're emitted.

If you're on 1.0.1+ and still seeing buffering, check whether your terminal is line-buffering output. In Jupyter/VS Code/JupyterLab, use `clear_output(wait=True) + display(...)` for reliable incremental rendering.

### How do I render a "Thinking" panel from reasoning events?

```python
for event in agent.stream(prompt):
    if event.type == "reasoning_started":
        print(f"🧠 Iteration {event.payload['iteration']} — thinking…")
    elif event.type == "reasoning_completed":
        print(f"🧠 Thought: {event.payload['content']}")
    elif event.type == "tool_called":
        print(f"▶ Calling {event.message}")
```

Run [`examples/02_streaming_with_reasoning.py`](https://github.com/shipiit/shipit_agent/blob/main/examples/02_streaming_with_reasoning.py) for a colored terminal renderer you can copy.

### Token-level reasoning streaming?

Not in v1.0. The current LLM adapters are non-streaming (`llm.complete()` returns once per iteration), so reasoning arrives as a **single event per iteration** with the full content. Token-level streaming requires adding a `.stream()` method to the LLM adapters and consuming chunks in the runtime — planned for a future release.

---

## Bedrock

### Why does my Bedrock agent crash on the third iteration with "toolResult blocks exceed toolUse blocks"?

This was a real bug in pre-1.0.1 versions. **Upgrade to v1.0.1+** — the runtime now guarantees every `toolUse` block gets a paired `toolResult`, even when:
- A tool fails (synthetic error result)
- The model hallucinates an unknown tool name (synthetic "tool not registered" result)
- The planner runs (output injected as user-role context, not orphan tool-result)

If you're on 1.0.1+ and still seeing the error, [open an issue](https://github.com/shipiit/shipit_agent/issues/new?template=bug_report.yml) with the full traceback.

### Which Bedrock model should I use?

- **`bedrock/openai.gpt-oss-120b-1:0`** — cheap, surfaces reasoning blocks, supports tool calling
- **`bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`** — more capable, more expensive, supports extended thinking via LiteLLM
- **`bedrock/meta.llama3-3-70b-instruct-v1:0`** — fast and cheap, no reasoning, weaker tool calling

### Do I need `boto3` installed?

Not directly. `BedrockChatLLM` uses LiteLLM under the hood, which has its own AWS client. You only need:

```bash
pip install 'shipit-agent[litellm]'
```

Plus your AWS credentials in env vars (`AWS_REGION_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) or via `AWS_PROFILE`.

---

## Production deployment

### Is `code_execution` safe for untrusted prompts?

**No.** `CodeExecutionTool` runs untrusted Python in a subprocess that inherits your environment, can read/write the workspace, and can make network requests. For production with untrusted input:

- Run shipit-agent **inside a Docker container** with no host filesystem mounts
- Restrict the workspace to a tmpfs volume
- Drop network access from the container
- Set `allow_shell=False`
- Consider running each agent invocation in a fresh container

For local dev and trusted internal use, the default config is fine.

### How do I prevent tool-call infinite loops?

`agent.max_iterations = N` (default 4). If the cap is reached while the model is still calling tools, the runtime gives it one more turn with `tools=[]` to force a final summary, so `run_completed` is never empty.

### How do I store credentials securely?

Use `FileCredentialStore` for local dev (file is read-only to the user, gitignored), or implement a custom `CredentialStore` backed by AWS Secrets Manager / HashiCorp Vault / Doppler / your secret store of choice. The protocol is two methods:

```python
class CredentialStore(Protocol):
    def get(self, name: str) -> CredentialRecord | None: ...
    def put(self, record: CredentialRecord) -> None: ...
```

### How do I monitor production runs?

Use `FileTraceStore` to capture every event with timestamps, then ship the trace files to your observability stack:

```python
from shipit_agent import Agent, FileTraceStore

agent = Agent(
    llm=llm,
    trace_store=FileTraceStore(root="/var/log/shipit/traces"),
    trace_id=f"run-{request_id}",
)
```

For real-time observability, write a custom `TraceStore` that ships events to Datadog / Honeycomb / OpenTelemetry as they're emitted.

---

## Troubleshooting

### "Missing environment variable for X" — what now?

The error tells you exactly which env var to set. Add it to your `.env` file or shell environment, then re-run. `build_llm_from_env()` walks upward from CWD to find `.env` so it works regardless of which directory you launch from.

### `gpt-4o-mini` describes a plan instead of calling tools

`gpt-4o-mini` is notoriously lazy about tool use. Three fixes:

1. **Force tool use:** `OpenAIChatLLM(model="gpt-4o-mini", tool_choice="required")`
2. **Disable the planner** (it primes the model to describe instead of execute): `agent.router_policy = RouterPolicy(auto_plan=False)`
3. **Use a stronger model:** `gpt-4o`, `o3-mini`, or any reasoning-capable model

### The docs site doesn't update after I push to main

Check https://github.com/shipiit/shipit_agent/actions and look for the `Docs` workflow. If it's failing, click into the failed run for the error. Common causes:

- Missing `mkdocs.yml` change pushed alongside docs files
- New page added to `docs/` but not added to `mkdocs.yml` nav
- `mkdocs build --strict` failing on a broken link — fix the link and re-push

### Gitleaks CI fails on a runtime file

If gitleaks flags a file under `.shipit_notebooks/`, `sessions/`, `traces/`, or `memory.json`, it's a false positive — those files contain scraped tool outputs (e.g. Pushly client-side IDs from CoinDesk pages) that look like API keys to the rule engine. The v1.0.1 `.gitleaks.toml` allowlist covers these paths. If a new false-positive pattern surfaces, add it to the `regexes` list in `.gitleaks.toml`.

---

## Contributing

### How do I submit a fix?

See [`CONTRIBUTING.md`](https://github.com/shipiit/shipit_agent/blob/main/CONTRIBUTING.md). TL;DR:

1. Fork + branch
2. `make install-hooks`
3. Make your change
4. `make check` (lint + test + gitleaks)
5. Open a PR

### How do I cut a release? (maintainers only)

```bash
make new-release VERSION=1.0.2    # bumps + tests + builds
# review the diff, edit CHANGELOG
git add -A && git commit -m "release: v1.0.2"
git push origin main
make tag                          # creates and pushes v1.0.2 git tag
make publish                      # uploads to PyPI (asks for confirmation)
make github-release               # creates GitHub Release with notes + dist files
```

Or one shot: `make ship-it`.

---

## Still stuck?

- 📖 [Full documentation](https://shipiit.github.io/shipit_agent/)
- 🐛 [Open a bug report](https://github.com/shipiit/shipit_agent/issues/new?template=bug_report.yml)
- 💬 [GitHub Discussions](https://github.com/shipiit/shipit_agent/discussions)
- 📋 [Tool catalog](tools/index.md)
- 📚 [Glossary](glossary.md)
