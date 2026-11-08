---
title: Interleaved thinking & context editing
description: Let Claude think between tool calls with interleaved_thinking + thinking_budget_tokens, and have Anthropic clear stale tool results server-side with context_management. Thinking blocks and budget surface in LLMResponse.metadata.
---

# Interleaved thinking & context editing

`AnthropicChatLLM` exposes two more Claude-API power
features: **interleaved thinking** (the model reasons *between* tool calls, not
just before its first answer) and **server-side context editing** (Anthropic
clears stale tool results for you, on its side of the wire).

## Interleaved thinking

Extended thinking lets Claude produce `thinking` blocks before answering.
**Interleaved** thinking extends that across a tool loop — the model can think,
call a tool, see the result, think again, and so on. It's enabled by pairing
two kwargs on `AnthropicChatLLM`:

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(
    model="claude-sonnet-5-5",
    thinking_budget_tokens=2048,     # turns on extended thinking
    interleaved_thinking=True,       # allow thinking between tool calls
)
```

The beta header `interleaved-thinking-2025-05-14` is attached **only when
`interleaved_thinking=True` *and* `thinking_budget_tokens` is set** — interleaved
thinking requires extended thinking to be on. With either flag off, the request
stays on the GA endpoint, unchanged.

> **Honest scope.** The adapter side of the round-trip is wired: response
> `thinking` blocks (with their signatures) are surfaced in
> `LLMResponse.metadata["thinking_blocks"]` and re-emitted first on assistant
> messages whose metadata carries them. Completing the round-trip across a
> *multi-turn* tool loop also needs the runtime to copy that metadata onto the
> next assistant message; until that propagation lands, treat interleaved
> thinking as a **degrade-gracefully passthrough** — it never breaks a run, and
> single-response thinking is fully captured.

### What surfaces in metadata

| Metadata key | When | Contents |
| --- | --- | --- |
| `metadata["thinking_budget_tokens"]` | `thinking_budget_tokens` set | The configured budget. |
| `metadata["thinking_blocks"]` | `interleaved_thinking=True` and blocks present | The full `thinking` / `redacted_thinking` blocks, including signatures, for round-tripping. |
| `response.reasoning_content` | any thinking present | The concatenated thinking text, which the runtime emits as `reasoning_started` / `reasoning_completed` events. |

## Context editing

Long tool loops bloat the context window with old tool results. `context_management`
hands that cleanup to Anthropic: pass a context-management config and the API
**clears stale tool results server-side**, so you don't have to truncate the
transcript yourself.

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(
    model="claude-sonnet-5-5",
    context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
)
```

When set, the config is forwarded as the `context_management` request param and
the `context-management-2025-06-27` beta header is attached automatically; the
call is routed to the beta endpoint. With `context_management=None` (the
default) nothing changes and the request is identical to legacy. This composes
with shipit's own client-side [context management](../guides/context-management.md)
— use either, or both.

## Provider note

Extended and interleaved thinking, and server-side context editing, are
**Anthropic** features (also reachable for Anthropic models via Bedrock /
LiteLLM). The equivalents on other providers are their **reasoning** modes:
OpenAI's reasoning models (o-series / GPT-5-class, via `reasoning_effort`) and
Gemini's thinking. shipit already captures reasoning content from all of them
into `response.reasoning_content` (see [Reasoning & thinking](../guides/reasoning.md)),
but the `interleaved_thinking` / `context_management` kwargs are Anthropic-specific.

## See also

- [Server-side tools](./server-side-tools.md) — Anthropic-hosted tools that run
  in Anthropic's sandbox.
- [Citations & Batch API](./citations-and-batch.md) — verifiable RAG and
  ~50%-cheaper bulk runs.
- [Reasoning & thinking](../guides/reasoning.md) — how reasoning content is
  captured across every provider.
- [Context management](../guides/context-management.md) — shipit's client-side
  context-window strategies.
