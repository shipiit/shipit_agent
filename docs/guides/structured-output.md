# Structured Output

All LLM adapters support `response_format` for requesting structured responses directly from the provider. This is useful when you need JSON output, validated schemas, or specific output formats.

## Usage

Pass `response_format` when calling an LLM adapter directly:

```python
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.models import Message

llm = OpenAIChatLLM(model="gpt-4o-mini")

response = llm.complete(
    messages=[Message(role="user", content="List 3 Python web frameworks")],
    response_format={"type": "json_object"},
)

import json
data = json.loads(response.content)
print(data)
# {"frameworks": ["Django", "Flask", "FastAPI"]}
```

## Provider support

| Provider | `response_format` support | Notes |
|---|---|---|
| OpenAI | `{"type": "json_object"}`, JSON Schema | Full support via API |
| Anthropic | Passed to API | Check Anthropic docs for supported formats |
| LiteLLM (all providers) | Passed through | Depends on underlying provider |
| SimpleEchoLLM | Accepted, ignored | Test/dev only |

## JSON Schema mode (OpenAI)

OpenAI supports strict JSON Schema validation:

```python
response = llm.complete(
    messages=[Message(role="user", content="Analyze this code")],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "code_analysis",
            "schema": {
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["language", "complexity", "issues"],
            },
        },
    },
)
```

## With LiteLLM providers

```python
from shipit_agent.llms import GeminiChatLLM

llm = GeminiChatLLM(model="gemini/gemini-1.5-pro")

response = llm.complete(
    messages=[Message(role="user", content="List capitals of G7 countries")],
    response_format={"type": "json_object"},
)
```

!!! note
    `response_format` is a direct LLM adapter feature. The agent runtime loop does not pass it through automatically — it's designed for direct LLM calls where you need structured output. Inside the agent loop, use tool outputs and system prompts to guide the format of the final answer.
