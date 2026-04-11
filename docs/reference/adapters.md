---
title: Model Adapters
description: Provider-specific LLM adapters for shipit_agent — OpenAI, Anthropic, Bedrock, Vertex AI, Gemini, Groq, Together, Ollama, LiteLLM, plus the SimpleEcho test stub.
---

# Model Adapters

`shipit_agent` ships with adapters for every major LLM provider. They
all implement the same `LLM` protocol, return the same
`LLMResponse` shape, and populate `LLMResponse.reasoning_content`
when the underlying model exposes reasoning blocks. Switching providers
is **one line in `.env`** — see the
[Quickstart](../getting-started/quickstart.md#6-switch-providers).

---

## The protocol

```python
class LLM(Protocol):
    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
```

```python
@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
```

You can implement your own adapter for any provider by satisfying that
protocol — the runtime doesn't care where the response came from.

---

## Adapter cheat sheet

| Adapter | Module | Backing SDK | Best at |
| --- | --- | --- | --- |
| [`OpenAIChatLLM`](#openaichatllm) | `shipit_agent.llms` | `openai` | OpenAI directly, fastest tool calling |
| [`AnthropicChatLLM`](#anthropicchatllm) | `shipit_agent.llms` | `anthropic` | Claude directly, extended thinking |
| [`BedrockChatLLM`](#bedrockchatllm) | `shipit_agent.llms` | `litellm` | AWS Bedrock — gpt-oss / Claude / Llama |
| [`VertexAIChatLLM`](#vertexaichatllm) | `shipit_agent.llms` | `litellm` | Google Vertex AI |
| [`GeminiChatLLM`](#litellm-backed-adapters) | `shipit_agent.llms` | `litellm` | Gemini API |
| [`GroqChatLLM`](#litellm-backed-adapters) | `shipit_agent.llms` | `litellm` | Groq's hosted Llama / Mixtral |
| [`TogetherChatLLM`](#litellm-backed-adapters) | `shipit_agent.llms` | `litellm` | Together AI |
| [`OllamaChatLLM`](#litellm-backed-adapters) | `shipit_agent.llms` | `litellm` | Local Ollama |
| [`LiteLLMChatLLM`](#litellmchatllm--litellmproxychatllm) | `shipit_agent.llms` | `litellm` | Generic LiteLLM SDK escape hatch |
| [`LiteLLMProxyChatLLM`](#litellmchatllm--litellmproxychatllm) | `shipit_agent.llms` | `litellm` | Self-hosted LiteLLM proxy server |
| [`SimpleEchoLLM`](#simpleecho-llm--shipitllm) | `shipit_agent.llms` | stdlib | Tests, demos, offline |
| [`ShipitLLM`](#simpleecho-llm--shipitllm) | `shipit_agent.llms` | stdlib | Echo with a custom prefix |

The fastest way to wire any of these is `build_llm_from_env()` —
provider switching becomes one env var. See
[Environment setup](../getting-started/environment.md).

---

## `OpenAIChatLLM`

Native OpenAI SDK adapter. Best when you have an OpenAI API key and
want the lowest possible latency on tool calling.

```python
from shipit_agent.llms import OpenAIChatLLM

llm = OpenAIChatLLM(
    model="gpt-4o-mini",
    api_key=None,                  # falls back to OPENAI_API_KEY env var
    reasoning_effort=None,         # auto-set to "medium" for o-series + gpt-5 + DeepSeek R1
    tool_choice=None,              # "auto" | "required" | "none" | dict
)
```

**Reasoning models** — auto-receive `reasoning_effort="medium"`:
`o1`, `o1-mini`, `o1-preview`, `o3`, `o3-mini`, `o4`, `o4-mini`,
`gpt-5*`, `deepseek-r1*`.

**Lazy `gpt-4o-mini`** — set `tool_choice="required"` to force at least
one tool call per turn. See [the FAQ](../faq.md#gpt-4o-mini-describes-a-plan-instead-of-calling-tools)
for the full set of fixes.

`SHIPIT_OPENAI_TOOL_CHOICE=required` is the env-var equivalent.

---

## `AnthropicChatLLM`

Native Anthropic SDK adapter. Best when you have an Anthropic API key
and want extended thinking + Claude's strict tool-use shape.

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(
    model="claude-opus-4-1",
    api_key=None,                    # falls back to ANTHROPIC_API_KEY env var
    max_tokens=4096,
    thinking_budget_tokens=None,     # set to enable extended thinking
)
```

**Extended thinking:** set `thinking_budget_tokens=2048` and the
adapter translates this to `thinking={"type": "enabled", "budget_tokens": 2048}`,
then extracts `thinking_blocks[*].thinking` from the response into
`reasoning_content`.

**Tool calling:** the adapter translates OpenAI-style tool schemas to
Anthropic's flat `{name, description, input_schema}` shape
automatically — your custom tools work without modification.

---

## `BedrockChatLLM`

```python
from shipit_agent.llms import BedrockChatLLM

llm = BedrockChatLLM(
    model="bedrock/openai.gpt-oss-120b-1:0",
)
```

Uses LiteLLM under the hood. Works with any Bedrock model that LiteLLM
supports. `modify_params=True` is set so LiteLLM helps with Bedrock's
strict tool-use pairing — the runtime's
[pairing invariant](architecture.md#1-tool-useresult-pairing) makes
this a safety net rather than a requirement.

**Recommended Bedrock models:**

| Model | Why |
| --- | --- |
| `bedrock/openai.gpt-oss-120b-1:0` | Cheap, surfaces reasoning blocks, supports tool calling |
| `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` | More capable, supports extended thinking via LiteLLM |
| `bedrock/meta.llama3-3-70b-instruct-v1:0` | Fast and cheap, no reasoning, weaker tool calling |

**Reasoning extraction** — the adapter handles three shapes
transparently:

1. Flat `reasoning_content` on the response message (gpt-oss / DeepSeek)
2. Anthropic-style `thinking_blocks[*].thinking`
3. `model_dump()` fallback — any `reasoning_content` /
   `thinking_blocks` key found in the pydantic dump

**Credentials** — set `AWS_REGION_NAME` (or `AWS_DEFAULT_REGION`) plus
the usual AWS credential env vars (or `AWS_PROFILE`). The adapter does
not need `boto3` directly because LiteLLM has its own AWS client.

---

## `VertexAIChatLLM`

```python
from shipit_agent.llms import VertexAIChatLLM

llm = VertexAIChatLLM(
    model="vertex_ai/gemini-1.5-pro",
    service_account_file="/path/to/sa.json",
    project_id="my-gcp-project",
    location="us-central1",
)
```

The adapter sets `GOOGLE_APPLICATION_CREDENTIALS` automatically so
`google-auth` picks it up. Works with any Vertex-hosted model that
LiteLLM supports.

`build_llm_from_env('vertex')` is the recommended path:

```bash
SHIPIT_LLM_PROVIDER=vertex
SHIPIT_VERTEX_CREDENTIALS_FILE=/path/to/sa.json
VERTEXAI_PROJECT=my-gcp-project
VERTEXAI_LOCATION=us-central1
```

---

## LiteLLM-backed adapters

All of these are thin `LiteLLMChatLLM` subclasses and inherit the same
reasoning extraction:

| Adapter | Default model | Notes |
| --- | --- | --- |
| `GeminiChatLLM` | `gemini/gemini-1.5-pro` | Needs `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| `GroqChatLLM` | `groq/llama-3.3-70b-versatile` | Needs `GROQ_API_KEY` |
| `TogetherChatLLM` | `together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo` | Needs `TOGETHERAI_API_KEY` |
| `OllamaChatLLM` | `ollama/llama3.1` | Local — runs against `http://localhost:11434` by default |

```python
from shipit_agent.llms import GeminiChatLLM, GroqChatLLM, OllamaChatLLM

llm = GeminiChatLLM(model="gemini/gemini-1.5-pro")
llm = GroqChatLLM(model="groq/llama-3.3-70b-versatile")
llm = OllamaChatLLM(model="ollama/llama3.1")
```

---

## `LiteLLMChatLLM` / `LiteLLMProxyChatLLM`

The generic LiteLLM escape hatch — point at any model that LiteLLM
supports. `LiteLLMProxyChatLLM` is the recommended class when you run
your own LiteLLM proxy server.

### Direct LiteLLM SDK

```python
from shipit_agent.llms import LiteLLMChatLLM

llm = LiteLLMChatLLM(
    model="bedrock/openai.gpt-oss-120b-1:0",
    api_key="…",
    custom_llm_provider=None,        # leave None unless your model needs it
)
```

### LiteLLM proxy server

```python
from shipit_agent.llms import LiteLLMProxyChatLLM

llm = LiteLLMProxyChatLLM(
    model="gpt-4o-mini",                # whatever the proxy routes to
    api_base="https://litellm.my-company.internal",
    api_key="sk-proxy-token",
    custom_llm_provider="openai",       # proxy speaks OpenAI
)
```

`build_llm_from_env('litellm')` auto-detects proxy mode when
`SHIPIT_LITELLM_API_BASE` is set. See the
[FAQ entry](../faq.md#how-do-i-use-my-own-litellm-proxy-server) for
the env-var contract.

---

## `SimpleEchoLLM` / `ShipitLLM`

Test stubs. They never call real APIs — they echo the last user
message back, never call tools, never produce reasoning. Use them in
tests, demos, and offline development.

```python
from shipit_agent.llms import ShipitLLM, SimpleEchoLLM

llm = SimpleEchoLLM()                   # echoes the last user message
llm = ShipitLLM(prefix="[shipit] ")     # echo with a custom prefix
```

Both are 100% deterministic — perfect for unit tests that need a
predictable LLM but don't care about quality.

---

## Choosing an adapter — quick guide

| You have / want | Use |
| --- | --- |
| OpenAI API key, lowest latency | `OpenAIChatLLM` |
| Anthropic API key, extended thinking | `AnthropicChatLLM` |
| AWS credentials, cheap reasoning | `BedrockChatLLM("bedrock/openai.gpt-oss-120b-1:0")` |
| GCP credentials | `VertexAIChatLLM` |
| Local laptop, no internet | `OllamaChatLLM` |
| Custom self-hosted proxy | `LiteLLMProxyChatLLM` |
| A model LiteLLM supports but no dedicated adapter | `LiteLLMChatLLM` |
| Tests / demos | `SimpleEchoLLM` |

---

## Implementing your own adapter

The protocol is small. The minimum viable adapter is ~30 lines:

```python
from dataclasses import dataclass
from typing import Any
from shipit_agent.llms.base import LLM, LLMResponse
from shipit_agent.models import Message, ToolCall

class MyLLM(LLM):
    def __init__(self, client: Any) -> None:
        self.client = client

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict] | None = None,
        system_prompt: str | None = None,
        metadata: dict | None = None,
    ) -> LLMResponse:
        resp = self.client.chat(
            messages=[m.to_dict() for m in messages],
            tools=tools or [],
        )
        return LLMResponse(
            content=resp.get("text", ""),
            tool_calls=[
                ToolCall(name=tc["name"], arguments=tc["arguments"])
                for tc in resp.get("tool_calls", [])
            ],
            metadata=resp.get("metadata", {}),
            reasoning_content=resp.get("reasoning"),
            usage=resp.get("usage", {}),
        )
```

That's it. Drop it into `Agent(llm=MyLLM(client))` and the runtime
treats it like any other adapter.

---

## Related

- [Reasoning guide](../guides/reasoning.md) — what reasoning looks like end-to-end
- [Environment setup](../getting-started/environment.md) — credential configuration
- [Architecture](architecture.md) — where adapters fit in the runtime
- [Quickstart — switch providers](../getting-started/quickstart.md#6-switch-providers)
- [FAQ — providers](../faq.md#providers)
