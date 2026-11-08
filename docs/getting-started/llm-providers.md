---
title: LLM providers — use any model
description: shipit_agent runs the SAME agent code on OpenAI, Anthropic, AWS Bedrock, Google Vertex, Gemini, Groq, Together, Ollama, and any LiteLLM-reachable model. Pick a provider two ways — a direct adapter class, or build_llm_from_env() driven by SHIPIT_LLM_PROVIDER — and swap providers in one line.
---

# LLM providers — use any model

shipit_agent is **provider-agnostic**. The `Agent`, `DeepAgent`, tools,
streaming, RAG, caching, and tracing layers never care which model is behind
the LLM — they only talk to the small `LLM` interface. That means you write
your agent **once** and run it on whichever provider you want.

There are two ways to get an LLM:

1. **Direct adapter class** — import the adapter and construct it. Explicit,
   great for code that pins one provider.
2. **`build_llm_from_env()`** — set `SHIPIT_LLM_PROVIDER` (plus that
   provider's credentials) in your `.env` and let the factory pick the adapter.
   Great for "swap providers without touching code."

Both come from `shipit_agent.llms`:

> **New: the provider catalog.** Every provider is now a declarative
> **profile** in a catalog directory — display name, auth env, adapter class,
> default model, and capabilities (vision, prompt-cache). `build_llm_from_env()`
> resolves through the catalog, you can **list and inspect** every provider from
> code, and you can **add a new provider by dropping in a directory** — no code
> edit. See [The provider catalog](#the-provider-catalog) below. Nothing about
> the two ways above changes; the catalog sits underneath them.

```python
from shipit_agent.llms import (
    build_llm_from_env,
    OpenAIChatLLM,
    AnthropicChatLLM,
    BedrockChatLLM,
    VertexAIChatLLM,
    GeminiChatLLM,
    GroqChatLLM,
    TogetherChatLLM,
    OllamaChatLLM,
    LiteLLMChatLLM,
    LiteLLMProxyChatLLM,
)
```

---

## Swap providers in one line

The rest of your agent code is **identical** regardless of provider. Only the
one line that builds the LLM changes:

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

llm = build_llm_from_env("openai")     # ← change "openai" to any provider below
# everything from here down never changes:
agent = Agent.with_builtins(llm=llm)
print(agent.run("Find today's Bitcoin price in USD.").output)
```

Or change nothing in code at all — set `SHIPIT_LLM_PROVIDER` in `.env` and call
`build_llm_from_env()` with no argument:

```bash
# .env
SHIPIT_LLM_PROVIDER=anthropic     # bedrock|openai|anthropic|gemini|vertex|groq|together|ollama|litellm
```

```python
llm = build_llm_from_env()             # reads SHIPIT_LLM_PROVIDER from .env
```

!!! note "Default provider"
    If `SHIPIT_LLM_PROVIDER` is unset, the factory defaults to **`bedrock`**.
    Pass an explicit provider (`build_llm_from_env("openai")`) to override
    `.env` for a single call.

---

## Every supported provider

| Provider | `SHIPIT_LLM_PROVIDER` | Adapter class | Required env vars | Default model |
| --- | --- | --- | --- | --- |
| OpenAI | `openai` | `OpenAIChatLLM` | `OPENAI_API_KEY` | `gpt-5.5` |
| Anthropic | `anthropic` | `AnthropicChatLLM` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| AWS Bedrock | `bedrock` | `BedrockChatLLM` | `AWS_REGION_NAME` (or `AWS_DEFAULT_REGION`) or `AWS_PROFILE` | `bedrock/openai.gpt-oss-120b-1:0` |
| Google Vertex | `vertex` | `VertexAIChatLLM` | creds file + `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION` | `vertex_ai/gemini-3.5-flash` |
| Google Gemini | `gemini` | `GeminiChatLLM` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini/gemini-3.5-flash` |
| Groq | `groq` | `GroqChatLLM` | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| Together | `together` | `TogetherChatLLM` | `TOGETHERAI_API_KEY` or `TOGETHER_API_KEY` | `together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo` |
| Ollama (local) | `ollama` | `OllamaChatLLM` | *none* — needs a local Ollama server | `ollama/llama3.1` |
| LiteLLM (proxy to ~everything) | `litellm` | `LiteLLMChatLLM` / `LiteLLMProxyChatLLM` | `SHIPIT_LITELLM_MODEL` (+ provider creds / `SHIPIT_LITELLM_API_BASE`) | *none — `SHIPIT_LITELLM_MODEL` required* |

Per-provider init snippets follow. Each shows **both** the direct adapter class
and the matching `build_llm_from_env()` env-var setup.

---

## The provider catalog

Under the factory, every provider is a **profile** — a small declarative record
of how to reach it. Each provider is its own clean directory:

```
shipit_agent/providers/catalog/<name>/
  profile.yaml     # display name, auth env, adapter class, default model, capabilities
  provider.py      # optional — only for providers that need imperative setup
```

### List and inspect providers

Discover every provider and its capabilities from code — perfect for building a
provider picker in a UI:

```python
from shipit_agent.providers import list_providers, get_profile

for p in list_providers():
    print(f"{p.icon} {p.name:10} {p.display_name:20} "
          f"{'vision ' if p.supports_vision else ''}"
          f"{'cache' if p.supports_prompt_cache else ''}")

openai = get_profile("openai")           # by name or alias (e.g. "gpt")
openai.require_env        # ['OPENAI_API_KEY']
openai.default_model      # 'gpt-5.5'
openai.fallback_models    # ['gpt-5.5']
openai.signup_url         # where a user gets a key
```

### Build from the catalog

`build_llm_from_env()` already resolves through the catalog. For a lower-level
call — say you have the settings as a dict — use `build_provider`:

```python
from shipit_agent.providers import build_provider

llm = build_provider("openai", config={"model": "gpt-5.5"})
llm = build_provider("bedrock", env={"AWS_REGION_NAME": "us-east-1"})
```

`config` is your settings (overrides), `env` defaults to `os.environ`. A missing
key raises the same clear error the factory always did.

### Add a new provider — no code edit

Drop a directory under `providers/catalog/` with one `profile.yaml`:

```yaml
# providers/catalog/deepseek/profile.yaml
profile_version: 1
name: deepseek
display_name: DeepSeek
description: DeepSeek chat + reasoning models via LiteLLM.
icon: "🐋"
adapter: shipit_agent.llms.litellm_adapter:LiteLLMChatLLM
default_model: deepseek/deepseek-chat
model_env: [SHIPIT_DEEPSEEK_MODEL]
require_env: [DEEPSEEK_API_KEY]
capabilities: {vision: false, prompt_cache: false}
signup_url: https://platform.deepseek.com/api_keys
```

That's it — the registry scans the directory, validates the profile (an invalid
one is **skipped with a diagnostic**, never a crash), and `build_provider("deepseek")`
works. Adding a provider is a data edit, not a pull request.

For a provider that needs imperative setup — AWS region discovery, a
package-missing fallback, multi-env credential resolution — add a sibling
`provider.py` exporting `build(profile, config, env) -> llm`; the profile then
carries just metadata. The bundled `bedrock`, `anthropic`, `vertex`, `openai`,
and `litellm` directories are the reference.

### Capabilities carried by every profile

| Field | Meaning |
| --- | --- |
| `supports_vision` | provider/model accepts image blocks |
| `supports_prompt_cache` | honours prompt caching |
| `default_max_tokens` | default output cap (0 = library default) |
| `fixed_temperature` | a provider that pins temperature records it here |
| `fallback_models` | ordered fallbacks (for a coming failover layer) |

---

### OpenAI

```python
from shipit_agent.llms import OpenAIChatLLM, build_llm_from_env

# Direct:
llm = OpenAIChatLLM(model="gpt-5.5")
# Force at least one tool call per turn (lazy models):
llm = OpenAIChatLLM(model="gpt-5.5", tool_choice="required")

# From env:
llm = build_llm_from_env("openai")
```

```bash
SHIPIT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
SHIPIT_OPENAI_MODEL=gpt-5.5          # optional
SHIPIT_OPENAI_TOOL_CHOICE=               # optional — "required" forces a tool call
```

OpenAI does **automatic** prompt caching; shipit surfaces the cache reads. See
[Prompt caching](../agent/prompt-caching.md).

---

### Anthropic

```python
from shipit_agent.llms import AnthropicChatLLM, build_llm_from_env

# Direct (prompt caching on by default for Claude):
llm = AnthropicChatLLM(model="claude-sonnet-5-5")
# Extended thinking:
llm = AnthropicChatLLM(model="claude-opus-5-5", thinking_budget_tokens=2048)

# From env:
llm = build_llm_from_env("anthropic")
```

```bash
SHIPIT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
SHIPIT_ANTHROPIC_MODEL=claude-sonnet-5-5    # optional
```

---

### AWS Bedrock

Bedrock authenticates with **AWS credentials**, not an API key — a region plus
your standard AWS access keys, an `AWS_PROFILE`, or an instance role.

```python
from shipit_agent.llms import BedrockChatLLM, build_llm_from_env

# Direct:
llm = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
# Claude on Bedrock (tool-pairing handled automatically):
llm = BedrockChatLLM(model="bedrock/google.gemma-4-31b")

# From env:
llm = build_llm_from_env("bedrock")
```

```bash
SHIPIT_LLM_PROVIDER=bedrock
AWS_REGION_NAME=us-east-1                 # or AWS_DEFAULT_REGION, or set AWS_PROFILE
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=                        # optional
SHIPIT_BEDROCK_MODEL=bedrock/openai.gpt-oss-120b-1:0    # optional
```

---

### Google Vertex AI

Vertex needs a service-account JSON file **plus** a project and a location.

```python
from shipit_agent.llms import VertexAIChatLLM, build_llm_from_env

# Direct:
llm = VertexAIChatLLM(
    model="vertex_ai/gemini-3.5-flash",
    service_account_file="/path/to/sa.json",
    project_id="my-gcp-project",
    location="us-central1",
)

# From env:
llm = build_llm_from_env("vertex")
```

```bash
SHIPIT_LLM_PROVIDER=vertex
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json   # or SHIPIT_VERTEX_CREDENTIALS_FILE
VERTEXAI_PROJECT=my-gcp-project                    # or GOOGLE_CLOUD_PROJECT
VERTEXAI_LOCATION=us-central1                      # or VERTEX_LOCATION / GOOGLE_CLOUD_LOCATION
SHIPIT_VERTEX_MODEL=vertex_ai/gemini-3.5-flash       # optional
```

The Vertex adapter handles the full Vertex catalog — Gemini, Claude-on-Vertex,
Llama-on-Vertex, etc. Claude-on-Vertex gets `cache_control` prompt caching too.

---

### Google Gemini

```python
from shipit_agent.llms import GeminiChatLLM, build_llm_from_env

# Direct:
llm = GeminiChatLLM(model="gemini/gemini-3.5-flash")

# From env:
llm = build_llm_from_env("gemini")
```

```bash
SHIPIT_LLM_PROVIDER=gemini
GEMINI_API_KEY=...                        # or GOOGLE_API_KEY
SHIPIT_GEMINI_MODEL=gemini/gemini-3.5-flash    # optional
```

---

### Groq

```python
from shipit_agent.llms import GroqChatLLM, build_llm_from_env

# Direct:
llm = GroqChatLLM(model="groq/llama-3.3-70b-versatile")

# From env:
llm = build_llm_from_env("groq")
```

```bash
SHIPIT_LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
SHIPIT_GROQ_MODEL=groq/llama-3.3-70b-versatile    # optional
```

---

### Together AI

```python
from shipit_agent.llms import TogetherChatLLM, build_llm_from_env

# Direct:
llm = TogetherChatLLM(
    model="together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo"
)

# From env:
llm = build_llm_from_env("together")
```

```bash
SHIPIT_LLM_PROVIDER=together
TOGETHERAI_API_KEY=...                    # or TOGETHER_API_KEY
SHIPIT_TOGETHER_MODEL=together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo    # optional
```

---

### Ollama (local models)

No API key — just a running local Ollama server.

```python
from shipit_agent.llms import OllamaChatLLM, build_llm_from_env

# Direct:
llm = OllamaChatLLM(model="ollama/llama3.1")

# From env:
llm = build_llm_from_env("ollama")
```

```bash
SHIPIT_LLM_PROVIDER=ollama
SHIPIT_OLLAMA_MODEL=ollama/llama3.1       # optional
```

---

### LiteLLM (proxy to ~everything)

LiteLLM routes to ~100 providers behind one interface. Use the direct
`LiteLLMChatLLM` for any LiteLLM-format model string, or `LiteLLMProxyChatLLM`
to point at a self-hosted LiteLLM proxy gateway. With `build_llm_from_env`, the
factory picks `LiteLLMProxyChatLLM` automatically when `SHIPIT_LITELLM_API_BASE`
is set, otherwise `LiteLLMChatLLM`.

```python
from shipit_agent.llms import (
    LiteLLMChatLLM,
    LiteLLMProxyChatLLM,
    build_llm_from_env,
)

# Direct — any LiteLLM model string:
llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-5-5")

# Direct — self-hosted LiteLLM proxy gateway:
llm = LiteLLMProxyChatLLM(
    model="gpt-5.5",                            # whatever the proxy routes to
    api_base="https://litellm.my-company.internal",
    api_key="sk-proxy-token",
    custom_llm_provider="openai",                   # proxy speaks OpenAI format
)

# From env (LiteLLMChatLLM, or LiteLLMProxyChatLLM if SHIPIT_LITELLM_API_BASE set):
llm = build_llm_from_env("litellm")
```

```bash
SHIPIT_LLM_PROVIDER=litellm
SHIPIT_LITELLM_MODEL=anthropic/claude-sonnet-5-5    # required
SHIPIT_LITELLM_API_KEY=                                    # optional
SHIPIT_LITELLM_API_BASE=                                   # set → LiteLLMProxyChatLLM
SHIPIT_LITELLM_CUSTOM_PROVIDER=                            # optional
```

LiteLLM forwards both cache-token shapes (Anthropic `cache_read_input_tokens`
and OpenAI `prompt_tokens_details.cached_tokens`), so cross-provider cost
accounting keeps working through the proxy.

---

## See also

- [Environment setup](environment.md) — `.env` discovery, credential
  requirements, and switching providers without restarting.
- [Quick start](quickstart.md) — get an agent running in five minutes on any
  provider.
- [Prompt caching](../agent/prompt-caching.md) — caching works across
  Anthropic, Bedrock, Vertex (`cache_control`), and OpenAI (automatic);
  LiteLLM forwards both.
