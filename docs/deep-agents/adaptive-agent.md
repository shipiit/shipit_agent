# AdaptiveAgent

Agent that creates new tools at runtime from Python code. When it needs a capability it doesn't have, it writes one.

## Quick start

```python
from shipit_agent.deep import AdaptiveAgent
from shipit_agent.tools.base import ToolContext

agent = AdaptiveAgent(llm=llm, can_create_tools=True)

fib = agent.create_tool(
    name="fibonacci",
    description="Calculate Nth Fibonacci number",
    code="""
    def fibonacci(n: int) -> str:
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return str(a)
    """,
)

# Test it
print(fib.run(ToolContext(prompt="test"), n=10).text)  # "55"

# Use in agent runs
result = agent.run("What is fibonacci of 20?")
```

## With built-in tools

```python
agent = AdaptiveAgent.with_builtins(llm=llm, can_create_tools=True)
# Has web search + code exec + dynamic tool creation
```

## Properties

| Property | Type | Description |
|---|---|---|
| `created_tools` | `list[CreatedTool]` | All dynamically created tools |
| `tools` | `list[Tool]` | All tools (including created) |

!!! note
    Code strings are auto-dedented, so indented code in notebooks works fine.
