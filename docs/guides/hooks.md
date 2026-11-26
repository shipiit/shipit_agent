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
    llm=OpenAIChatLLM(model="gpt-5.5"),
    hooks=hooks,
)

result = agent.run("What is the weather in Tokyo?")
```

## Hook types

The `Agent` class has thirteen hook points. The first five are the ones most code needs; the rest match the SDK API's hook events one for one, so a hook written for either works the same way.

| Hook | Signature | When it fires, and what it may return |
|---|---|---|
| `user_prompt` | `fn(prompt: str)` | When a prompt arrives. Return text to rewrite it, or `False` to block the run. |
| `before_llm` | `fn(messages: list, tools: list)` | Before each model call. |
| `after_llm` | `fn(response: LLMResponse)` | After each model call returns. |
| `before_tool` | `fn(name: str, arguments: dict)` | Before a tool runs. Return a decision to allow, deny or ask, or new arguments. |
| `permission_request` | `fn(name: str, arguments: dict, reason: str)` | When a call would wait for a person. Return `{"decision": "allow"}` or `{"decision": "deny", "reason": ...}` to settle it. |
| `after_tool` | `fn(name: str, result: ToolResult)` | After a tool returns, whether it succeeded or failed. |
| `post_tool_use` | `fn(name: str, arguments: dict, result: ToolResult)` | After the `after_tool` hooks. Return `{"updated_output": text}` to replace what the model reads, or text to add to it. |
| `post_tool_failure` | `fn(name: str, arguments: dict, error: str)` | When a tool fails. Return text to add to the failed result, such as how to recover. |
| `subagent_start` | `fn(agent_type: str, task: str)` | Before a sub-agent starts. Return `False` to refuse it, or text to add to its brief. |
| `subagent_stop` | `fn(agent_type: str, task: str, output: str, error: str)` | When a sub-agent ends. It only observes. |
| `pre_compact` | `fn(messages: list, info: dict)` | Just before older turns are summarized. Return text to add to the summarizer's instructions. |
| `notification` | `fn(message: str, notification_type: str)` | When a call is left waiting for approval, so a host can page someone. It only observes. |
| `stop` | `fn(answer: str)` | When the agent is about to finish. Return a reason to keep it working. |

Each has a decorator named `on_` plus the hook's name:

```python
from shipit_agent import AgentHooks

hooks = AgentHooks()


@hooks.on_user_prompt
def add_the_branch(prompt: str) -> str:
    return f"{prompt}\n\nYou are on the branch fix/login."


@hooks.on_post_tool_failure
def how_to_recover(name: str, arguments: dict, error: str) -> str | None:
    if name == "bash":
        return "If the command is missing, look in pyproject.toml for the right one."
    return None


@hooks.on_permission_request
def approve_test_runs(name: str, arguments: dict, reason: str) -> dict | None:
    if name == "bash" and str(arguments.get("command", "")).startswith("pytest"):
        return {"decision": "allow"}
    return None
```

Hook callbacks on the `Agent` class are plain functions; an `async def` hook raises a `TypeError` when it is called, so a check can never be skipped silently. The SDK API's hooks are async; session start and end hooks exist only there ([Agent SDK API](agent-sdk.md#session-start-and-end)).

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
`None` to let it finish, or a reason to send it back to work:

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
