---
title: Prompt caching
description: Cache the stable prefix (system prompt + tools) on Anthropic, Bedrock, and Vertex so repeated turns read it back at ~10% of the input price. On by default for Claude-family models (v1.0.11); cross-provider cost accounting — OpenAI's automatic cache reads surfaced — added in v1.0.12.
---

# Prompt caching

New in **v1.0.11**, shipit_agent caches the **stable prefix** of every
request — the system prompt plus the tool definitions — so repeated turns
don't re-pay full input price for tokens that never change. On a tool-using
agent the prefix is large and identical across iterations, so this is one of
the cheapest, highest-leverage wins available.

There are **two halves** to caching, and they have different provider reach:

- **Write side** — injecting `cache_control` breakpoints so the provider
  *stores* the prefix. This is an Anthropic API shape: it works across
  **Anthropic**, **Bedrock**, and **Vertex** Claude, and is **on by default**
  for the Claude family.
- **Read side** — *accounting* for cached tokens so cache reads bill at the
  cheaper rate. This is **cross-provider**: Anthropic/Bedrock/Vertex report
  `cache_read_input_tokens` directly, and shipit now also surfaces
  **OpenAI's automatic prompt caching** by reading
  `prompt_tokens_details.cached_tokens` into the same key. So caching is
  cross-provider — not Anthropic-only.

> **TL;DR** — cached prefix tokens are read back at roughly **10% of the
> input price**. A long system prompt + tool schemas, reused across a 10-turn
> agent loop, drops from ~10× the prefix cost to ~1×.

## Turning it on

It's already on for Claude-family models — you don't have to do anything. The
flag is exposed so you can be explicit or opt out:

```python
from shipit_agent.llms import AnthropicChatLLM, LiteLLMChatLLM

# Anthropic adapter — caching on by default.
llm = AnthropicChatLLM(model="claude-sonnet-4-20250514", prompt_caching=True)

# LiteLLM adapter — caching applied only to Anthropic/Claude models it routes
# to (Bedrock and Vertex Claude included); a no-op for other providers.
llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-4-20250514", prompt_caching=True)

# Opt out:
llm = AnthropicChatLLM(model="claude-sonnet-4-20250514", prompt_caching=False)
```

Under the hood the adapter injects `cache_control: {"type": "ephemeral"}`
breakpoints on the system message and the last tool definition, so the whole
stable prefix is cached. The `LiteLLMChatLLM` adapter only injects breakpoints
for Anthropic/Claude models (`anthropic` or `claude` in the model name); for
every other provider the **write side** is a no-op and nothing breaks — but the
read-side accounting still applies (see below).

## Provider support

Keep the two halves separate. The **write side** (`cache_control` breakpoints)
is a Claude API shape; the **read side** (surfacing cached tokens for the
`CostTracker`) is cross-provider.

| Provider | Write side — `cache_control` | Read side — `cache_read_input_tokens` |
| --- | --- | --- |
| **Anthropic** | Explicit `cache_control` breakpoints, **default on** for Claude | From `usage.cache_read_input_tokens` |
| **Bedrock** (Claude) | Explicit `cache_control` (via LiteLLM) | From `usage.cache_read_input_tokens` |
| **Vertex** (Claude) | Explicit `cache_control` (via LiteLLM) | From `usage.cache_read_input_tokens` |
| **OpenAI** | n/a — **automatic** prompt caching, no `cache_control` needed | Surfaced from `prompt_tokens_details.cached_tokens` |
| **LiteLLM** | Injected only for Anthropic/Claude models it routes to | Forwards **both** shapes — Anthropic `cache_read_input_tokens` and OpenAI `prompt_tokens_details.cached_tokens` |
| Gemini / Groq / Ollama / others | n/a | Surfaced when the provider reports a cached-token count in either shape |

The key change: **OpenAI does automatic prompt caching** on its side — you don't
add `cache_control`, the platform caches repeated prefixes for you. shipit reads
`usage.prompt_tokens_details.cached_tokens` and writes it into
`usage["cache_read_input_tokens"]` — the *same* key the `CostTracker` already
reads for Anthropic — so OpenAI cache reads bill at the cheaper rate with no
extra wiring. `LiteLLMChatLLM` forwards whichever shape the underlying provider
returns.

## Cost accounting

Each call's usage carries two cache fields that flow straight into the
[CostTracker](../guides/cost-tracking.md):

| Usage key | Meaning | Billed at |
| --- | --- | --- |
| `usage["cache_creation_input_tokens"]` | Tokens written into the cache on the first turn | a small write premium |
| `usage["cache_read_input_tokens"]` | Tokens read back from the cache on later turns | **~10% of input** |

`CostTracker` prices `cache_read` at roughly a tenth of the input rate — for
example Claude Opus is `$15.00` / 1M input vs `$1.50` / 1M cache-read, and
Sonnet is `$3.00` vs `$0.30`. The first turn pays a one-time write cost; every
subsequent turn reuses the prefix at the cheap read rate.

The example below uses `AnthropicChatLLM`, but the read-side accounting is
cross-provider — OpenAI's automatic cache reads and LiteLLM-forwarded counts
flow through the same `cache_read_input_tokens` key (see
[LLM providers](../getting-started/llm-providers.md)).

```python
from shipit_agent import Agent, CostTracker
from shipit_agent.llms import AnthropicChatLLM

tracker = CostTracker()
llm = AnthropicChatLLM(model="claude-sonnet-4-20250514")  # caching on
agent = Agent(llm=llm, tools=[...], hooks=tracker.as_hooks())

agent.run("First task.")    # writes the prefix into the cache
agent.run("Second task.")   # reads the prefix back at ~10% input price

totals = tracker.total_tokens
print("cache reads:", totals["cache_read_tokens"])
print("cache writes:", totals["cache_write_tokens"])
print("total $:", tracker.total_cost)
```

## Notes

- **Stable prefix only.** Caching helps the parts that don't change — system
  prompt + tools. The per-turn user message and tool results are not cached.
- **Two halves, different reach.** `cache_control` breakpoint injection (the
  *write* side) is Claude-only — Anthropic, Bedrock, and Vertex. Cached-token
  *accounting* (the *read* side) is cross-provider: OpenAI's automatic cache
  reads surface under the same `cache_read_input_tokens` key, and LiteLLM
  forwards both shapes.
- **Backward compatible.** Adapters that don't understand caching simply
  ignore the flag, and the cache usage keys default to `0`.

## See also

- [Cost tracking](../guides/cost-tracking.md) — `CostTracker`, budgets, and
  the `as_hooks()` wiring.
- [Model adapters](../reference/adapters.md) — the LLM adapter surface.
