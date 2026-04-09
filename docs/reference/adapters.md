# Model Adapters

SHIPIT Agent ships with adapters for every major LLM provider. All adapters implement the same `LLM` protocol and populate `LLMResponse.reasoning_content` when the underlying model exposes reasoning blocks.

## Protocol

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
```

## `OpenAIChatLLM` (native SDK)

```python
from shipit_agent.llms import OpenAIChatLLM

llm = OpenAIChatLLM(
    model="gpt-4o-mini",
    api_key=None,                   # falls back to OPENAI_API_KEY env var
    reasoning_effort=None,          # auto-set to "medium" for o1/o3/o4/gpt-5/deepseek-r1
    tool_choice=None,               # "auto" | "required" | "none" | dict
)
```

**Reasoning models:** `o1`, `o1-mini`, `o1-preview`, `o3`, `o3-mini`, `o4`, `o4-mini`, `gpt-5*`, `deepseek-r1*` — all auto-receive `reasoning_effort="medium"`.

**Tool choice:** set `tool_choice="required"` to force at least one tool call per turn. Recommended for `gpt-4o-mini` which is otherwise lazy about tool use.

## `AnthropicChatLLM` (native SDK)

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(
    model="claude-opus-4-1",
    api_key=None,                   # falls back to ANTHROPIC_API_KEY env var
    max_tokens=4096,
    thinking_budget_tokens=None,    # set to enable extended thinking
)
```

**Extended thinking:** set `thinking_budget_tokens=2048` to enable Claude's extended thinking mode. The adapter translates this to `thinking={"type": "enabled", "budget_tokens": 2048}` and extracts `thinking_blocks[*].thinking` from the response into `reasoning_content`.

**Tool calling:** the adapter translates OpenAI-style tool schemas to Anthropic's flat `{name, description, input_schema}` shape automatically.

## `BedrockChatLLM` / `LiteLLMChatLLM`

```python
from shipit_agent.llms import BedrockChatLLM

llm = BedrockChatLLM(
    model="bedrock/openai.gpt-oss-120b-1:0",
)
```

Uses LiteLLM under the hood. Works with any Bedrock model that LiteLLM supports. `modify_params=True` is set to help with Bedrock's strict tool-pairing, but the runtime's pairing guarantees make this a safety net rather than a requirement.

**Reasoning extraction:** handles three shapes:

1. Flat `reasoning_content` on the response message (OpenAI / gpt-oss / DeepSeek via LiteLLM)
2. Anthropic `thinking_blocks[*].thinking`
3. `model_dump()` fallback — any `reasoning_content` / `thinking_blocks` key found in the pydantic dump

## Other LiteLLM-backed adapters

All of these are thin `LiteLLMChatLLM` subclasses and support the same reasoning extraction:

| Adapter | Default model |
|---|---|
| `GeminiChatLLM` | `gemini/gemini-1.5-pro` |
| `GroqChatLLM` | `groq/llama-3.3-70b-versatile` |
| `TogetherChatLLM` | `together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo` |
| `OllamaChatLLM` | `ollama/llama3.1` |

## `SimpleEchoLLM`

For tests and demos — echoes the last user message back, never calls tools. No reasoning.

```python
from shipit_agent.llms import SimpleEchoLLM

llm = SimpleEchoLLM()
```

## Related

- [Reasoning guide](../guides/reasoning.md) — what reasoning looks like end-to-end
- [Environment setup](../getting-started/environment.md) — credential configuration
