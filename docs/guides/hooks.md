# Hooks & Middleware

`AgentHooks` provides a lightweight callback system for injecting behavior before and after LLM calls and tool calls. No subclassing, no abstract base classes — just callback lists with decorator registration.

## Quick start

```python
from shipit_agent import Agent, AgentHooks
from shipit_agent.llms import OpenAIChatLLM

hooks = AgentHooks()

@hooks.on_before_llm
def log_llm_call(messages, tools):
    print(f"Calling LLM with {len(messages)} messages, {len(tools)} tools")

@hooks.on_after_llm
def track_tokens(response):
    usage = response.usage
    if usage:
        print(f"Tokens: {usage.get('total_tokens', 0)}")

@hooks.on_before_tool
def log_tool_start(name, arguments):
    print(f"Running {name}...")

@hooks.on_after_tool
def log_tool_end(name, result):
    print(f"{name} returned {len(result.output)} chars")

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    hooks=hooks,
)

result = agent.run("What is the weather in Tokyo?")
```

## Hook types

| Hook | Signature | When it fires |
|---|---|---|
| `before_llm` | `fn(messages: list, tools: list)` | Before each LLM completion call |
| `after_llm` | `fn(response: LLMResponse)` | After each LLM completion returns |
| `before_tool` | `fn(name: str, arguments: dict)` | Before a tool is executed |
| `after_tool` | `fn(name: str, result: ToolResult)` | After a tool returns (success or error) |

## Registration

Two ways to register hooks:

=== "Decorator style"

    ```python
    hooks = AgentHooks()

    @hooks.on_before_llm
    def my_hook(messages, tools):
        ...
    ```

=== "Append style"

    ```python
    hooks = AgentHooks()
    hooks.before_llm.append(lambda msgs, tools: print("calling LLM"))
    ```

Both are equivalent. The decorator returns the original function, so you can still call it directly.

## Common patterns

### Cost tracking

```python
total_cost = {"tokens": 0}

@hooks.on_after_llm
def accumulate(response):
    total_cost["tokens"] += response.usage.get("total_tokens", 0)

agent.run("Do something complex")
print(f"Total tokens used: {total_cost['tokens']}")
```

### Rate limiting

```python
import time

last_call = {"time": 0.0}

@hooks.on_before_llm
def rate_limit(messages, tools):
    elapsed = time.time() - last_call["time"]
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    last_call["time"] = time.time()
```

### Content filtering

```python
@hooks.on_after_tool
def filter_pii(name, result):
    if "email" in result.output.lower():
        print(f"Warning: {name} output may contain PII")
```

### Guardrails

```python
BLOCKED_TOOLS = {"code_execution", "workspace_files"}

@hooks.on_before_tool
def block_dangerous_tools(name, arguments):
    if name in BLOCKED_TOOLS:
        raise PermissionError(f"Tool {name} is blocked by policy")
```

## Via the profile builder

```python
from shipit_agent import AgentProfileBuilder, AgentHooks

hooks = AgentHooks()
hooks.before_llm.append(my_logger)

profile = (
    AgentProfileBuilder("monitored-agent")
    .hooks(hooks)
    .build_profile()
)
```

## Works with async too

`AgentHooks` works identically with `AsyncAgentRuntime`. The hook callbacks themselves are synchronous — the async runtime calls them inline between awaits.
