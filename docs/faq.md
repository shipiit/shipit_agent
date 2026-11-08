---
description: Answers to the questions people ask most about ShipIt Agent, from choosing a model to running agents in production.
---

# FAQ

## The basics

### What is ShipIt Agent?

An open-source Python runtime for agents: a model that calls tools in a loop until a task is done. It ships the loop, 66 tools, permissions, hooks, sessions, memory, context management and an OS sandbox, and it works with any model that supports tool calling. See the [Overview](index.md).

### How does it relate to the Claude Agent SDK?

shipit implements the Claude Agent SDK's API under the same names: `query()`, `AgentClient`, `AgentOptions`, hooks, permission modes, `@tool` and `create_sdk_mcp_server`. The difference is underneath. The SDK drives the Claude Code CLI as a subprocess and runs Claude; shipit runs its own loop in your process and runs any model. [Agent SDK API](guides/agent-sdk.md#where-shipit-differs) lists every difference.

### How is it different from LangChain, LangGraph or CrewAI?

Those are toolkits for assembling an agent from parts. shipit is the agent, ready to run: one call gives you a working coding or research agent with safe defaults, and you change what you need. It has no graph DSL; you write ordinary Python around `run()` and `stream()`.

### Which Python versions?

3.11 and newer.

### Is it production-ready?

It is used in production, with over 5,000 tests and a benchmark of 18 agent tasks. Before you ship, set the limits (`max_turns`, `max_budget_usd`), choose a permission mode, and turn on the [sandbox](guides/sandbox.md) if the agent runs commands. MIT licensed.

## Models

### Which model should I use?

Any model with tool calling. On the 18-task benchmark, Claude Sonnet 5.5 and Gemma 4 31B both pass every task: Claude in fewer turns, Gemma at about a seventh of the cost. Start with a strong model; move to a cheaper one once your task works, and check it with the [benchmark](guides/benchmark.md).

### How do I switch models?

Change one line: the model name in `AgentOptions(model=...)`, or `SHIPIT_LLM_PROVIDER` and the provider's model variable. Tools, prompts and sessions stay the same. [Configure a model](getting-started/environment.md).

### Can I run a local model?

Yes, through Ollama (`SHIPIT_LLM_PROVIDER=ollama`) or any OpenAI-compatible server through LiteLLM. Small local models call tools less reliably; test them on your task.

### The model describes what it will do instead of doing it.

Some models narrate a tool call instead of making it. Set `require_tool_call=True` to require a tool call on the first step, or `required_tools=["read_file"]` to name the tools that must run before the agent may finish.

### Why do I see the model's thinking on one provider and not another?

Only some models expose their reasoning, and only when it is turned on (`thinking=` for Claude). Where it exists, it arrives as `reasoning_completed` events. [Reasoning](guides/reasoning.md).

## Tools

### How do I write a tool?

Wrap a function: `FunctionTool.from_callable(my_function)`. The docstring and type hints become the schema. Async functions work too. For more control, write a class. [Custom tools](guides/custom-tools.md).

### My agent has many tools and every request is expensive.

Every tool's schema is sent with every request. Give the agent only the tools it needs, or set `deferred_tools=True`: a small core stays loaded and the rest are listed by name and loaded with `tool_search` when needed. [Tool search](guides/tool-search.md).

### Why was a bash command refused, or why did it ask for approval?

Commands that delete files, discard git work, push, publish, use sudo, write outside the project or send data out need approval. Allow specific ones with a rule such as `Bash(npm run build)`, approve in code with `permission_callback`, or turn on the [sandbox](guides/sandbox.md), where commands run without asking because they cannot write outside the project. [Permissions](guides/permissions.md).

### Why does `edit_file` refuse to edit?

It edits only files read in this run, and refuses if the file changed on disk since. This keeps the agent from overwriting work it has not seen. The agent reads the file again and retries.

### Is running model-written code safe?

Not without a boundary. Turn on the OS [sandbox](guides/sandbox.md) for `bash` and `run_code`, or call `run_code` with `sandbox: true` to run in a disposable Docker container with no network. Commands also get a scrubbed environment, so host secrets are not visible to them.

## Agent behaviour

### The agent stops before the task is really done.

Add a stop hook that checks the answer and sends the agent back with a reason, up to three times. [Hooks](guides/hooks.md#keep-going-until-its-really-done-stop-hooks). For coding agents, `verify_before_stop=True` refuses to finish a turn that edited code without a fresh passing test run.

### The agent repeats the same call.

shipit already suppresses identical repeated calls and tells the model. If a run keeps circling, set `max_turns`, and check that tool errors say what to do next: a model retries an error it cannot act on.

### Can the agent ask me a question?

Yes. The `ask_user` tool asks a question and waits for the answer; with the SDK API, the question arrives in your `can_use_tool` callback as `AskUserQuestion`. In an unattended run, it is told nobody can answer and proceeds on its best assumption.

### How do I keep a long run within the context window?

Older turns are compacted into a summary as the window fills, long tool output is clipped and saved to files, and `clear_tool_results=` clears old results once used. `optimized=True` sets these from the model's real window. [Context management](guides/context-management.md).

## Sessions and memory

### How do I continue a conversation later?

Give the agent a `session_store` and a `session_id`. The next run with the same id picks up where the last ended, even in a new process. [Sessions](agent/sessions.md).

### How does an agent remember things across conversations?

Three ways: project instructions in `SHIPIT.md`, `AGENTS.md` or `CLAUDE.md`; facts the agent saves with the `memory` tool into a `memory_store`; and `AgentMemory`, which your code fills. [Memory](agent/memory.md).

## Running in production

### How do I show progress in a UI?

Stream it: `agent.stream()` yields events as they happen, and `chat_session().stream_packets(..., transport="sse")` yields packets ready for a browser. [Streaming](agent/streaming.md).

### How do I serve an agent as an API?

`shipit serve` exposes an agent as an OpenAI-compatible endpoint with streaming, so any OpenAI client can call it.

### How do I cap cost?

`max_budget_usd` stops a run at a dollar amount and `max_task_tokens` at a token count. Every run's summary reports its tokens and `estimated_cost_usd`.

### How do I keep credentials safe?

Keep keys in the environment or a `CredentialStore`, never in prompts. shipit does not write keys to logs, events or traces, and the commands the agent runs do not inherit your environment. Pass the variables a command needs with `env=`.

### How do I monitor runs?

Every event can be streamed to your logging, a `trace_store` keeps each run's trace, and LangSmith or OpenTelemetry exporters are available as extras.

## Troubleshooting

### "Missing environment variable for …"

The provider's credential is not set. The message names the variable; set it in the shell or in `.env`.

### "Install `anthropic` to use AnthropicChatLLM"

The provider's package is missing: `pip install 'shipit-agent[anthropic]'`. shipit never quietly answers with another provider.

### "Command rejected: this command does nothing"

The model called bash with a placeholder such as `:` instead of a command. It is told to put the real command there, or to write text when it only wants to think, and it corrects itself in the next turn.

### "Tool … requires human approval … no one can approve it in this run"

The call needed approval and nothing could give it: no callback, no approval queue. The model finishes the rest of the task and names what is left. Add a rule or a callback to allow such calls.

## Still stuck?

Search these docs, read the [examples](agent/examples.md), or [open an issue](https://github.com/shipiit/shipit_agent/issues) with the code, the model and the events of the failing run.
