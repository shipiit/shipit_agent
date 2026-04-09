# Creating Custom Tools

A SHIPIT Agent tool is just a Python class with three things: a `name`, a `schema()` method, and a `run(context, **kwargs)` method.

## Minimal tool

```python
from shipit_agent.tools.base import ToolContext, ToolOutput


class AddNumbersTool:
    name = "add_numbers"
    description = "Add two numbers and return the sum."
    prompt_instructions = "Use this for simple arithmetic when code_interpreter is overkill."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"},
                    },
                    "required": ["a", "b"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        result = float(kwargs["a"]) + float(kwargs["b"])
        return ToolOutput(
            text=f"The sum is {result}",
            metadata={"a": kwargs["a"], "b": kwargs["b"], "sum": result},
        )
```

Attach it to an agent:

```python
from shipit_agent import Agent

agent = Agent(llm=llm, tools=[AddNumbersTool()])
```

## Anatomy

### `name`
The function name the LLM will call. Keep it snake_case and descriptive.

### `description`
One-line summary used by the LLM to decide whether to call this tool. Also used by `ToolSearchTool` for relevance scoring.

### `prompt_instructions`
Longer guidance on *when* to use the tool. Shown to the LLM via the system prompt and used by `ToolSearchTool`.

### `schema()`
Returns an OpenAI-compatible function schema. All providers (OpenAI, Anthropic, Bedrock, Gemini) accept this shape — adapters translate as needed.

### `run(context, **kwargs)`
Executes the tool. Returns a `ToolOutput(text, metadata)`.

- `context: ToolContext` — runtime context with `prompt`, `system_prompt`, `metadata`, `state`, `session_id`
- `**kwargs` — the arguments the LLM passed (matching your schema)

## `FunctionTool` wrapper

For one-off tools, wrap a plain function:

```python
from shipit_agent import FunctionTool

def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

tool = FunctionTool.from_function(
    multiply,
    name="multiply",
    description="Multiply two numbers.",
)

agent = Agent(llm=llm, tools=[tool])
```

## Error handling

- **Raise for transient errors** (network blips, rate limits) — the runtime's `RetryPolicy` will retry automatically and emit `tool_retry` events.
- **Return a `ToolOutput` with error text for permanent failures** (invalid URL, missing file) — this lets the LLM see the error and self-correct on the next turn.
- **Never silently swallow errors** — downstream tools can't reason about missing data.

```python
def run(self, context, **kwargs):
    try:
        result = self._do_work(kwargs["url"])
    except ValueError as exc:
        # Permanent error — return clean output, don't raise
        return ToolOutput(
            text=f"Error: {exc}",
            metadata={"error": str(exc), "url": kwargs["url"]},
        )
    return ToolOutput(text=result, metadata={"url": kwargs["url"]})
```

## Making tools interactive

Set `metadata["interactive"] = True` to pause the agent and emit an `interactive_request` event:

```python
return ToolOutput(
    text="Waiting for user confirmation…",
    metadata={
        "interactive": True,
        "kind": "approval",
        "question": "Delete all files? (yes/no)",
    },
)
```

The event payload lets your UI render a prompt and collect input before resuming.

## Bedrock tool-pairing safety

The runtime guarantees every `toolUse` block gets a paired `toolResult` — even if your tool raises an unhandled exception. You don't need to worry about Bedrock's strict pairing invariant; the runtime handles it.

## Discoverable via `tool_search`

Every tool's `name + description + prompt_instructions` is automatically indexed by `ToolSearchTool`. Write clear descriptions and instructions and your tool will surface when the agent asks for relevant capabilities.

## Related

- [Prebuilt tools](prebuilt-tools.md) — tools that ship with SHIPIT
- [Tool search](tool-search.md) — how discovery works
