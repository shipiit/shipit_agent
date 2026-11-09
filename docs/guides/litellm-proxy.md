---
title: LiteLLM proxy — bring your own URL + key
description: Point every shipit-agent Agent, Autopilot run, and crew at your self-hosted LiteLLM proxy. One URL, one key, every upstream model your company routes.
---

# LiteLLM proxy — bring your own URL + key

If your company runs a **self-hosted LiteLLM proxy** (`litellm --config`)
as a central gateway for upstream models, every `Agent`, `Autopilot`,
and `ShipCrew` in shipit-agent can point at it. You keep credential
management, rate-limiting, routing, cost tracking, and auditing on the
proxy — shipit-agent just speaks OpenAI-compatible HTTP to it.

> **TL;DR** — three fields: `model`, `api_base`, `api_key`. Everything
> else stays exactly the same as any other provider.

---

## The three fields

| Field | What it is | Example |
| --- | --- | --- |
| `model` | The model alias the proxy routes — whatever shows up in your proxy's `config.yaml` `model_list:` | `gpt-4o-mini`, `claude-sonnet-5-5`, `internal-router-v2` |
| `api_base` | Your proxy URL, the HTTP(S) endpoint that speaks OpenAI format | `https://litellm.my-company.internal` |
| `api_key` | Bearer token the proxy accepts for this caller | `sk-proxy-abc123...` |

---

## Three ways to wire it

### 1. Factory + settings dict (declarative)

Best when the config comes from environment, a config file, or a
settings store. The factory picks `LiteLLMProxyChatLLM` automatically
when `api_base` is set.

```python
from shipit_agent.llms import build_llm_from_settings

llm = build_llm_from_settings({
    "provider": "litellm",
    "model": "gpt-5.5",
    "api_base": "https://litellm.my-company.internal",
    "api_key": "sk-proxy-abc123...",
    "custom_llm_provider": "openai",   # proxy speaks OpenAI format
}, provider="litellm")
```

### 2. Direct class (imperative)

Best when you need full control or are building your own factory.

```python
from shipit_agent.llms import LiteLLMProxyChatLLM

llm = LiteLLMProxyChatLLM(
    model="gpt-5.5",
    api_base="https://litellm.my-company.internal",
    api_key="sk-proxy-abc123...",
    custom_llm_provider="openai",
)
```

### 3. Environment variables (zero code)

Best for containers / cronjobs / CI. Set these and call
`build_llm_from_env()` — the factory detects proxy mode automatically
when `SHIPIT_LITELLM_API_BASE` is present.

```bash
export SHIPIT_LLM_PROVIDER=litellm
export SHIPIT_LITELLM_MODEL=gpt-5.5
export SHIPIT_LITELLM_API_BASE=https://litellm.my-company.internal
export SHIPIT_LITELLM_API_KEY=sk-proxy-abc123...
```

```python
from shipit_agent.llms import build_llm_from_env

llm = build_llm_from_env()
```

---

## Plug into everything

The returned `llm` implements the standard `LLM` protocol — drop it
into any shipit-agent construct without further change.

### Agent

```python
from shipit_agent import Agent

agent = Agent(
    llm=llm,
    tools=[],    # or your tool list
    prompt="You are a helpful assistant.",
)
print(agent.run("Hello via our LiteLLM proxy.").output)
```

### Autopilot (long-running, goal-driven)

```python
from shipit_agent import Goal
from shipit_agent.autopilot import Autopilot, BudgetPolicy

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Summarise the last 7 days of customer feedback.",
        success_criteria=["Top 3 themes", "Action items"],
    ),
    budget=BudgetPolicy(max_seconds=1800, max_dollars=2.0),
)
result = autopilot.run(run_id="feedback-digest")
```

### ShipCrew

Pass the proxy LLM as the crew's `coordinator_llm`, and give each crew agent the same `llm`. See [ShipCrew](../deep-agents/ship-crew.md).

---

## Direct LiteLLM (without a proxy)

If you want LiteLLM's provider adapters but not a proxy in front,
use `LiteLLMChatLLM` directly. Any model string LiteLLM accepts works.

```python
from shipit_agent.llms import LiteLLMChatLLM

llm = LiteLLMChatLLM(
    model="openai/gpt-5.5",
    api_key=os.environ["OPENAI_API_KEY"],
)

# or
llm = LiteLLMChatLLM(model="groq/llama-3.3-70b-versatile")
llm = LiteLLMChatLLM(model="ollama/llama3.1")
llm = LiteLLMChatLLM(model="bedrock/us.amazon.nova-lite-v1:0")
```

The same factory call with `provider="litellm"` and **no** `api_base`
picks `LiteLLMChatLLM` instead of the proxy variant.

---

## How the factory decides

`build_llm_from_settings` reads `provider="litellm"` and branches:

1. `api_base` present → **`LiteLLMProxyChatLLM`** (OpenAI-compatible HTTP to your proxy).
2. `api_base` absent   → **`LiteLLMChatLLM`**      (direct LiteLLM SDK, talks to the upstream provider).

So you can share the same settings shape across environments — set
`SHIPIT_LITELLM_API_BASE` only in the environments that route through
the proxy.

---

## Retries and transient errors

Both LiteLLM adapters re-raise transient upstream errors (`429`, `500`,
`502`, `503`, `529`, plus `RateLimitError` / `ServiceUnavailable` /
`InternalServerError`) as `ConnectionError`, so the runtime's
`RetryPolicy` catches them and retries automatically. That means a flaky
proxy or an upstream rate-limit hit won't crash a long-running
Autopilot run — you'll see it in `tool_failed` / retry events instead.

---

## Related

- [Environment setup](../getting-started/environment.md) — every supported `SHIPIT_*` variable.
- [Autopilot](../autopilot/index.md) — wraps any LLM adapter, LiteLLM included.
- [Cost tracking](cost-tracking.md) — dollar accounting for any provider.
- [FAQ](../reference/adapters.md#litellm-proxy-server) — short recipe form.
