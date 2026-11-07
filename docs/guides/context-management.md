# Context Window Management

Long-running agents can exhaust the LLM's context window as tool results accumulate. SHIPIT Agent provides token usage tracking and automatic message compaction to handle this gracefully.

## Token usage tracking

Every `LLMResponse` now carries a `usage` dict with token counts from the provider:

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(llm=OpenAIChatLLM(model="gpt-4o-mini"))

for event in agent.stream("Research quantum computing"):
    if event.type == "run_completed":
        usage = event.payload.get("usage", {})
        print(f"Prompt tokens:     {usage.get('prompt_tokens', 0)}")
        print(f"Completion tokens: {usage.get('completion_tokens', 0)}")
        print(f"Total tokens:      {usage.get('total_tokens', 0)}")
```

Usage is accumulated across all iterations of the agent loop and reported in
the `run_completed` event. The totals also include
`cache_read_input_tokens` and `cache_creation_input_tokens`, so cached-prefix
savings remain visible after a multi-step run.

## Optimized long-running setup

For a large tool catalogue, enable the safe optimized preset:

```python
agent = Agent.for_project(
    llm=OpenAIChatLLM(model="gpt-4.1"),
    project_root="/path/to/repo",
    optimized=True,
)

chat = agent.chat_session(session_id="main")
chat.send("Review this repository")
chat.send("Continue by fixing the highest-priority issue")
```

This enables progressive code-mode tool discovery, chooses the model's known
context window for checkpoint compaction, raises the default loop budget to
eight iterations, and runs independent calls concurrently with a six-call
ceiling. Each model-visible result is limited to 16,000 characters and a
parallel group shares a 48,000-character budget. Complete sanitized results
remain in `AgentResult.tool_results` and live events; large results are also
saved under `.shipit/tool-results/`, and the bounded model extract includes the
recovery path. Pass `code_mode`, `context_window_tokens`, `max_iterations`,
`parallel_tool_execution`, `max_tool_output_chars`,
`max_tool_output_group_chars`, or `persist_large_tool_outputs` explicitly to
override these defaults.

Optimized project agents also default to durable project-local stores:

- `.shipit/sessions/<session-id>.json` keeps canonical multi-turn history.
- `.shipit/memory.json` keeps facts explicitly persisted by tools.

Recreate the agent and reuse the same session ID to resume after a process
restart. Session IDs are intentionally caller-supplied so different users or
workstreams never share history accidentally.

## Automatic message compaction

When `context_window_tokens` is set, the runtime automatically compacts older messages when the model's input budget reaches 85%:

```python
agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    context_window_tokens=128000,  # gpt-4o's context window
)
```

### How compaction works

1. Before each LLM call, the runtime estimates the token count of all messages
2. The model's output allowance is reserved before calculating the input budget
3. At 85% of that budget, a turn-boundary checkpoint condenses older messages
4. A six-section handoff preserves goals, constraints, progress, decisions, next steps, and critical context
5. Canonical history remains intact; only the replay window uses the checkpoint
6. The `context_compacted` event reports the message and token reduction

```
Before compaction:                  After compaction:
─────────────────                   ─────────────────

system: "You are helpful"           system: "You are helpful"
user: "Research X"                  user (compacted): "[web_search]: Top 3..
assistant: "Let me search"                            [open_url]: Page con.."
tool[web_search]: "Top 3 results.." assistant: "Based on the results..."
tool[open_url]: "Page content..."   tool[code_exec]: "Output: 42"
assistant: "Based on the results.." user: "Now analyze the data"
tool[code_exec]: "Output: 42"
user: "Now analyze the data"
```

### When to set it

| Model | Suggested `context_window_tokens` |
|---|---|
| GPT-4o / GPT-4o-mini | `128000` |
| Claude 3.5 / Claude Opus 4 | `200000` |
| Gemini 1.5 Pro | `1000000` |
| Llama 3.1 70B | `128000` |
| Bedrock gpt-oss-120b | `128000` |

Set to `0` (default) to disable compaction entirely.

## Clearing old tool results

Every turn re-sends the whole conversation, so a long task keeps paying for
files it read many turns ago. Compaction only steps in near the context
limit; clearing works long before that, on every provider:

```python
from shipit_agent import Agent
from shipit_agent.context.tool_result_clearing import ToolResultClearing

agent = Agent(llm=llm, clear_tool_results=True)            # the defaults below
agent = Agent(llm=llm, clear_tool_results=ToolResultClearing(
    trigger_tokens=30_000,     # start once uncleared tool results pass this
    keep=3,                    # the most recent results always stay whole
    min_result_tokens=100,     # smaller results are not worth clearing
    exclude_tools=("memory",), # never clear these
))
```

With the SDK API, pass it through `AgentOptions(agent_options={"clear_tool_results": True})`.

- Only the request changes. The session's history keeps every result.
- A cleared result becomes a one-line note naming the tool and what it
  looked at, such as `[Earlier read_file result for src/app.py cleared to
  save context. Call it again if you need it.]`.
- Clearing goes down to half the trigger, and the point never moves back,
  so the request's prefix changes once per batch and prompt caches keep
  hitting in between. Each batch emits a `tool_results_cleared` event.
- It is off by default. Measured on Gemma 4 31B with clearing at 8,000
  tokens: a 40-turn run fell from 907k to 574k input tokens (−37%) with the
  same calls, but on tasks that finish in 11 to 19 turns the difference went
  both ways (−17% to +22%), within run-to-run variance. Turn it on for long
  runs, and measure your own workload first:
  `python -m scripts.bench.run <provider> <model> --clear-tool-results 8000`.

On Anthropic, `AnthropicChatLLM(context_management=...)` does the same on
the server instead.

## Cost tracking with hooks

Combine usage tracking with hooks for detailed cost monitoring:

```python
from shipit_agent import Agent, AgentHooks

MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},  # per 1M tokens
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

hooks = AgentHooks()
costs = {"total_usd": 0.0}

@hooks.on_after_llm
def track_cost(response):
    model = response.metadata.get("model", "")
    rates = MODEL_COSTS.get(model, {"input": 0, "output": 0})
    prompt_cost = response.usage.get("prompt_tokens", 0) / 1_000_000 * rates["input"]
    completion_cost = response.usage.get("completion_tokens", 0) / 1_000_000 * rates["output"]
    costs["total_usd"] += prompt_cost + completion_cost

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    hooks=hooks,
)
agent.run("Do something complex with multiple tool calls")
print(f"Total cost: ${costs['total_usd']:.4f}")
```

## Provider support

| Provider | `usage` populated | Fields |
|---|---|---|
| OpenAI | Yes | `prompt_tokens`, `completion_tokens`, `total_tokens` |
| Anthropic | Yes | `prompt_tokens`, `completion_tokens`, `total_tokens` |
| LiteLLM (Bedrock, Gemini, etc.) | Yes | `prompt_tokens`, `completion_tokens`, `total_tokens` |
| SimpleEchoLLM (dev/test) | No | Empty dict |
