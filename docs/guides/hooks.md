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

agent = Agent(
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
| `user_prompt` | `fn(prompt: str)` | Rewrite or deny the incoming prompt before the model receives it |
| `stop` | `fn(answer: str)` | When the agent is about to finish; return a reason to keep it working |

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

## Keep going until it's really done (stop hooks)

A stop hook runs when the agent is about to give its final answer. Return
`None` to let it finish, or a reason to send it back to work, in the spirit of
Claude Code's `Stop` hooks:

```python
hooks = AgentHooks()

@hooks.on_stop
def must_cite(answer: str):
    if "http" not in answer:
        return "Cite at least one source link before answering."
    return None  # done

agent = Agent(llm=llm, hooks=hooks)
```

The reason is added to the conversation as `Not done yet: <reason>` and the run
continues. A hook can also return `{"decision": "block", "reason": "..."}`.

- Each block emits a `stop_blocked` event with the reason.
- A run is sent back at most `MAX_STOP_CONTINUATIONS` (3) times; after that it
  finishes and emits `stop_unresolved` once, so a hook that never relents
  cannot loop a run.
- A hook that raises lets the run finish and emits `stop_hook_error`.
- Hooks are not consulted on the last allowed iteration.

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

This includes ordinary `Agent.run`, `stream`, `arun`, and `astream`, not only
the built-in-tools factory. Keep callbacks fast: slow network calls or sleeps
inside a callback block the async event loop. Returning an awaitable raises
`TypeError`; an `async def` policy must not be silently treated as approval.

## Custom policies with ordinary Agent

```python
from shipit_agent import Agent, AgentHooks

hooks = AgentHooks()

@hooks.on_user_prompt
def check_request(prompt):
    if len(prompt) > 100_000:
        return {"decision": "deny", "reason": "Request exceeds this application's limit."}

@hooks.on_before_tool_matching("delete_*|send_*")
def require_review(name, arguments):
    return {"decision": "ask", "reason": "This action needs review."}

@hooks.on_after_llm
def record_usage(response):
    usage_logger(response.usage)  # your application-owned logging function

agent = Agent(llm=llm, tools=tools, hooks=hooks)
```

Configure your application's approval handler when using `ask`; a hook does
not grant approval by itself. No provider-specific hook implementation is needed.

Before-tool hooks run in registration order. Return a decision with
`updated_arguments` to rewrite the call. Later hooks and the permission engine
see those rewritten arguments. Deny wins over ask, and ask wins over allow;
later rewrites do not erase an earlier approval requirement.

### Output transformations and boundaries

Replacing output through a string, output/text dictionary, or `ToolOutput`
clears a stale `model_text` excerpt. A dictionary or `ToolOutput` can explicitly
supply a new `model_text` if a separate compact model view is desired.

Post-tool hooks run **after execution**. They cannot undo side effects or retract
raw output deltas already streamed to subscribers. Do not rely on them alone to
keep secrets out of logs/UI: redact at the tool source or buffer/filter events
before forwarding them. Hook code is trusted application Python, not sandboxed.
Create separately scoped callback state for different users; cloned agents can
share callback objects. Model hooks are not a durable billing ledger.

Ordinary callback exceptions propagate. Stop-hook exceptions are the documented
exception: they emit `stop_hook_error` and allow finishing. Stop hooks are quality
checks, not a security boundary, and their continuations can add token usage.

## Match and transform tool output

Matcher hooks accept glob patterns separated by `|`. Post-tool hooks may
return a string, `ToolOutput`, `ToolResult`, or an output/metadata dictionary;
the transformed result is what guardrails and the model see.

```python
@hooks.on_before_tool_matching("bash|edit_*")
def audit_mutation(name, arguments):
    print(name, arguments)

@hooks.on_after_tool_matching("github|secret_*")
def sanitize(name, result):
    return {
        "output": redact(result.output),
        "metadata": {"redacted_by_hook": True},
    }
```
