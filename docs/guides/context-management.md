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
        cache = event.payload.get("prompt_cache", {})
        print(f"Prompt tokens:     {usage.get('prompt_tokens', 0)}")
        print(f"Completion tokens: {usage.get('completion_tokens', 0)}")
        print(f"Total tokens:      {usage.get('total_tokens', 0)}")
        print(f"Cache mode:        {cache.get('mode')}")
        print(f"Cache supported:   {cache.get('supported')}")
        print(f"Cache hit:         {cache.get('hit')}")
```

Usage is accumulated across all iterations of the agent loop and reported in
the `run_completed` event. The totals also include
`cache_read_input_tokens` and `cache_creation_input_tokens`, so cached-prefix
savings remain visible after a multi-step run.

The `prompt_cache` object removes ambiguity from zero counters:

- `supported=false, mode="unsupported"` means the selected model cannot cache
  this request path. This is currently the case for Gemma 4 on
  `bedrock-mantle`.
- `supported=true, hit=false` means the provider returned cache accounting but
  this run did not read a cached prefix. Check minimum prefix size, prefix
  stability, and TTL.
- `hit=true` means `read_tokens` were served from cache.
- `hit=null, usage_reported=false` means the provider did not return enough
  information to prove either a hit or a miss.
- `supported=null, mode="provider_managed"` means the generic adapter cannot
  guarantee capability; the provider's usage response remains authoritative.

Native Anthropic and Anthropic-family models through LiteLLM use explicit
ephemeral cache breakpoints by default. OpenAI uses automatic prompt caching
and SHIPIT reads `prompt_tokens_details.cached_tokens` in both streaming and
non-streaming responses. Amazon Bedrock caching is model-specific; unsupported
models are not sent speculative cache fields.

## Provider-aware cache configuration

SHIPIT does not send one provider's cache fields to every model. Each adapter
resolves a cache policy and exposes it in `usage_tick` and `run_completed`:

```python
from shipit_agent.llms import AnthropicChatLLM, LiteLLMChatLLM, OpenAIChatLLM

claude = AnthropicChatLLM("claude-sonnet-4", prompt_caching=True)

openai = OpenAIChatLLM(
    "gpt-5",
    prompt_cache_key="shipit-repo-agent-v1",
    prompt_cache_retention="24h",
)

gemini = LiteLLMChatLLM("gemini/gemini-2.5-flash")
bedrock_claude = LiteLLMChatLLM(
    "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0"
)
```

LiteLLM translates explicit `cache_control` blocks to Bedrock `cachePoint`
blocks and Gemini cached content on supported routes. OpenAI, Azure OpenAI,
DeepSeek, and xAI use automatic caching and do not receive explicit markers.

For a newly supported provider/model, opt in without changing SHIPIT's model
classifier:

```python
llm = LiteLLMChatLLM(
    "bedrock/your-new-cache-capable-model",
    prompt_cache_strategy="explicit",
)
```

Use that override only after verifying the selected model supports caching.
`prompt_cache_strategy` accepts `"auto"` (default), `"automatic"`,
`"explicit"`, or `"disabled"`. `prompt_caching=False` disables SHIPIT cache
directives. Provider minimum prefix sizes still apply and providers may skip
caching below their thresholds. See the
[LiteLLM prompt-caching guide](https://docs.litellm.ai/docs/completion/prompt_caching)
and [Amazon Bedrock prompt-caching guide](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html).

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
| OpenAI | Yes | Automatic caching; cached reads reported when the API returns `cached_tokens` |
| Anthropic | Yes | Explicit breakpoints enabled by default; reads and writes reported |
| LiteLLM Anthropic / Bedrock Claude | Yes | Explicit markers translated to native cache controls |
| LiteLLM Gemini / Vertex Gemini | Yes | Explicit markers translated to Google cached content |
| LiteLLM OpenAI / Azure / DeepSeek / xAI | Yes | Automatic/provider-managed caching |
| Bedrock Mantle Gemma 4 | Yes | Prompt caching unsupported; status is explicit in `prompt_cache` |
| Other LiteLLM providers | Yes | Provider-managed; capability and usage depend on the selected model |
| SimpleEchoLLM (dev/test) | No | Empty dict |
