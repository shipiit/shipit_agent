# Reasoning & Thinking Steps

When the underlying LLM surfaces reasoning content, the runtime extracts it automatically and emits `reasoning_started` / `reasoning_completed` events — so your UI can render a live "Thinking" panel without any manual wiring.

## Which models produce reasoning?

| Provider | Reasoning-capable models | How it's surfaced |
|---|---|---|
| **OpenAI** | `o1`, `o1-mini`, `o1-preview`, `o3`, `o3-mini`, `o4`, `o4-mini`, `gpt-5*`, DeepSeek R1 via compat endpoints | `message.reasoning_content` on chat.completions |
| **Anthropic** | `claude-opus-4-1`, `claude-3.7-sonnet` with extended thinking enabled | `thinking_blocks[*].thinking` |
| **AWS Bedrock** | `bedrock/openai.gpt-oss-120b-1:0`, `bedrock/anthropic.claude-*` | Via LiteLLM, surfaces as `reasoning_content` |
| **DeepSeek** | `deepseek-r1` | `message.reasoning_content` |

Models that don't expose reasoning simply won't emit `reasoning_*` events — no error, no warning.

## Zero-config extraction

All three LLM adapters (`OpenAIChatLLM`, `AnthropicChatLLM`, `LiteLLMChatLLM` / `BedrockChatLLM`) share a common `_extract_reasoning()` helper that handles:

1. **Flat `reasoning_content`** on the response message (OpenAI / gpt-oss / DeepSeek via LiteLLM)
2. **Anthropic `thinking_blocks[*].thinking`** (Claude extended thinking)
3. **`model_dump()` fallback** — any `reasoning_content` / `thinking_blocks` key found in the pydantic dump

The extracted text is stored on `LLMResponse.reasoning_content`, and the runtime emits `reasoning_started` + `reasoning_completed` events for every non-empty value.

## OpenAI reasoning models

`OpenAIChatLLM` automatically sets `reasoning_effort="medium"` when the model name matches a reasoning pattern:

```python
from shipit_agent.llms import OpenAIChatLLM

# Auto-enables reasoning_effort="medium"
llm = OpenAIChatLLM(model="o3-mini")

# Override if needed
llm = OpenAIChatLLM(model="o3-mini", reasoning_effort="high")

# Force tool use (gpt-4o-mini is lazy about tool calls)
llm = OpenAIChatLLM(model="gpt-4o-mini", tool_choice="required")
```

## Anthropic extended thinking

Anthropic requires you to explicitly enable thinking and set a budget:

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(
    model="claude-opus-4-1",
    thinking_budget_tokens=2048,   # enables extended thinking
)
```

The adapter translates this to `thinking={"type": "enabled", "budget_tokens": 2048}` in the API call and extracts all `thinking` blocks from the response.

## Rendering a "Thinking" panel

```python
for event in agent.stream(prompt):
    if event.type == "reasoning_started":
        print(f"🧠 Iteration {event.payload['iteration']} — thinking…")
    elif event.type == "reasoning_completed":
        print(f"🧠 Thought: {event.payload['content']}")
    elif event.type == "tool_called":
        print(f"▶ Calling {event.message}")
```

## Caveats

### Non-streaming reasoning

SHIPIT Agent's LLM layer is currently non-streaming (`llm.complete()` returns once per iteration). Reasoning arrives as a **single `reasoning_completed` event per iteration** with the full content, not as a drip of deltas.

If you need token-level reasoning streaming (to match a "Thinking" panel that updates as the model thinks), the LLM adapter would need a `.stream()` method and the runtime would need to consume it chunk-by-chunk. Planned for a future release.

### Model silence

If a reasoning-capable model returns an empty reasoning block (e.g. the task was too simple), no `reasoning_*` events fire. This is correct behavior — don't treat absence as a bug.

### `gpt-4o-mini` has no reasoning

`gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`, and most pre-o1 models do **not** produce reasoning content. They'll run the tool loop normally but won't emit `reasoning_*` events. Use an o-series or `gpt-5` model if you need visible thinking.

## Related

- [Streaming guide](streaming.md) — event reference
- [Model adapters reference](../reference/adapters.md) — adapter-specific kwargs
