---
title: Server-side tools
description: Anthropic-hosted tools — web_search, code_execution, computer_use, bash, text_editor — that run inside Anthropic's own sandbox. Zero local infrastructure; server tool use and results surface in LLMResponse.metadata; required beta headers are attached automatically. New in v1.0.12.
---

# Server-side tools

New in **v1.0.12**, shipit_agent can declare **Anthropic-hosted server-side
tools**. Unlike ordinary client-side tools — which the model *requests* and your
process *executes* in a tool loop — server-side tools run inside **Anthropic's
own sandbox**. The model invokes them, Anthropic runs them, and the results come
back **inline in the same response**. There is **zero local infrastructure**: no
browser to drive, no container to spin up, no client-side execution loop.

> **TL;DR** — `from shipit_agent.llms import web_search, code_execution,
> computer_use, bash, text_editor`. Pass any of them in the `tools=` list you
> hand to `AnthropicChatLLM.complete(...)` (mixed freely with client-side
> tools). The adapter forwards them as-is, attaches the required beta headers,
> and surfaces server tool use/results in `LLMResponse.metadata`.

## The helpers

The constructor helpers live in `shipit_agent.llms` (re-exported from
`shipit_agent.llms.server_tools`). Each returns a plain dict in the exact
Anthropic API shape, verified against the `anthropic` 0.79.0 SDK:

| Helper | Anthropic `type` | Beta header | Notes |
| --- | --- | --- | --- |
| `web_search(max_uses=5, **extra)` | `web_search_20250305` | none (GA) | Hosted web search; `max_uses` caps searches per request. `allowed_domains` / `blocked_domains` / `user_location` forwarded verbatim. |
| `code_execution(**extra)` | `code_execution_20250522` | `code-execution-2025-05-22` | Runs code in Anthropic's sandbox. |
| `computer_use(display_width_px, display_height_px, *, display_number=None, **extra)` | `computer_20250124` | `computer-use-2025-01-24` | Screen-driving computer use; width/height required by the SDK type. |
| `bash(**extra)` | `bash_20250124` | none | Hosted bash tool. |
| `text_editor(**extra)` | `text_editor_20250728` | none | Hosted file editor; the SDK requires the name `str_replace_based_edit_tool` (the helper sets it for you). |

```python
from shipit_agent.llms import AnthropicChatLLM, web_search, code_execution

llm = AnthropicChatLLM(model="claude-sonnet-4-20250514")

response = llm.complete(
    messages=[...],
    tools=[
        web_search(max_uses=3, allowed_domains=["docs.anthropic.com"]),
        code_execution(),
        # ...mix in your own client-side tools here, too.
    ],
)

print(response.content)
print(response.metadata.get("server_tool_use"))      # what the model ran
print(response.metadata.get("server_tool_results"))  # what came back inline
```

## How declarations are routed

A server-side tool is just a dict that carries a top-level `"type"` key
(`is_server_tool(tool)` checks exactly that). Client-side tools follow the
OpenAI `{"function": {...}}` / flat shape and never have a top-level `"type"`.
The adapter uses this to decide per tool whether to **translate** the schema (for
client-side tools) or **forward it as-is** (for server-side tools). You can mix
both kinds freely in one `tools=` list.

### Beta headers are handled for you

Some server tools require a beta header; the adapter assembles them
automatically from the tools present:

- `web_search` is **generally available** — no beta header.
- `code_execution` needs `code-execution-2025-05-22`.
- `computer_use` needs `computer-use-2025-01-24`.

When any server tool needs a beta, the request is routed to
`client.beta.messages.create` with the right `betas=[...]`; with no betas
required, the call stays on the GA endpoint and is byte-identical to a plain
request. (`required_betas(tools)` returns the de-duplicated, order-stable list
the adapter uses.) Older SDKs without a beta client degrade gracefully — the
betas are forwarded as an `anthropic-beta` header instead.

## What surfaces in metadata

Server-side tool activity is **not** run through your local tool loop. Instead
the adapter parses the response's server blocks and attaches them to
`LLMResponse.metadata`:

| Metadata key | Contents |
| --- | --- |
| `metadata["server_tool_use"]` | The `server_tool_use` blocks — what the model invoked server-side. |
| `metadata["server_tool_results"]` | The inline result blocks (`web_search_tool_result`, `code_execution_tool_result`, `bash_code_execution_tool_result`, `text_editor_code_execution_tool_result`). |

Both keys are **only present when non-empty**, so a response with no server-tool
activity carries exactly the legacy metadata. The model's final text answer
(grounded in those server-side results) is in `response.content` as usual.

## Provider note

These helpers emit **Anthropic API shapes**. They work with `AnthropicChatLLM`,
and are reachable for **Anthropic models via Bedrock / LiteLLM** routing as
well. They are **not** a universal cross-provider abstraction — other providers
expose their own native server tools (OpenAI's hosted tools, Gemini's
grounding / code execution), with different request shapes. Use the helper that
matches the model you're calling.

## When to use

- **Grounded answers without a search stack** — `web_search()` lets Claude
  research in Anthropic's sandbox; no scraper, proxy, or search API to run.
- **Sandboxed compute with zero infra** — `code_execution()` runs code
  server-side; you never install Docker or manage a runner.
- **Hosted editing / shell** — `text_editor()` and `bash()` for file and shell
  operations inside Anthropic's environment.
- **Screen control** — `computer_use()` for Anthropic-driven computer use. (For
  a self-hosted, library-level browser/desktop loop instead, see
  [Browser automation](./computer-use.md) and the
  [computer-use tool](../tools/computer-use.md).)

## See also

- [Citations & Batch API](./citations-and-batch.md) — the other v1.0.12
  Claude-API passthroughs.
- [Interleaved thinking & context editing](./interleaved-thinking.md) — extended
  thinking between tool calls and server-side context editing.
- [Model adapters](../reference/adapters.md) — the LLM adapter surface.
