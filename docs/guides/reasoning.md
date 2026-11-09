---
description: Turn on a model's thinking, control how much it thinks, and show it in your interface.
---

# Reasoning

Some models think before they answer, and some of those show their thinking. When a response includes it, shipit emits a `reasoning_completed` event with the text, so an interface can show a "thinking" panel with no extra work.

## Turning it on

**Anthropic models** think when you ask them to. Current models use adaptive thinking, where the model decides how much to think; `effort` sets the depth.

```python
from shipit_agent.llms import AnthropicChatLLM

llm = AnthropicChatLLM(model="claude-sonnet-5-5", thinking="adaptive", effort="high")
```

Older Anthropic models take a fixed budget instead: `thinking_budget_tokens=4000`. Give a budget to a model that rejects budgets and shipit sends adaptive thinking instead. `interleaved_thinking=True` lets the model think between tool calls, not only at the start of a turn.

With the SDK API: `AgentOptions(model="claude-sonnet-5-5", thinking="adaptive", effort="high")`, or `max_thinking_tokens=` for a budget.

**OpenAI reasoning models** (`o`-series and `gpt-5`) reason by default; `reasoning_effort` sets how much:

```python
from shipit_agent.llms import OpenAIChatLLM

llm = OpenAIChatLLM(model="gpt-5.5", reasoning_effort="high")
```

**Through LiteLLM and Bedrock**, models that return `reasoning_content`, such as gpt-oss and DeepSeek R1, show it with no setting.

## Showing it

```python
for event in agent.stream("Why does the cache miss on every request?"):
    if event.type == "reasoning_completed":
        print("thinking:", event.payload["content"])
    elif event.type == "tool_called":
        print("calling:", event.payload["tool"])
    elif event.type == "text_delta":
        print(event.payload["chunk"], end="", flush=True)
```

Thinking arrives whole, as one `reasoning_completed` event per step, before that step's tool calls or answer. The answer itself streams as `text_delta`.

With the SDK API, thinking is a `ThinkingBlock` in the `AssistantMessage`'s content.

## Things to know

- **Not every model shows its thinking.** A model that does not expose it simply emits no `reasoning_*` events.
- **Thinking costs output tokens.** Use high effort where the task needs it, not by default.
- **Simple steps may have no thinking** even with it on; that is the model's choice.
- **Thinking is not narration.** shipit never presents a model's reasoning as something it did; `progress_summaries=True` adds short progress events built from what actually happened.
