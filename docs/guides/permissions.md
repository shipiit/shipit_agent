---
description: Decide which tool calls run, which are refused and which ask first, with modes, rules, callbacks and approval queues.
---

# Permissions

Every tool call passes a permission gate before it runs. The gate allows it, denies it, or asks: a person or your code decides. Read-only tools are allowed without asking; what happens to the rest is up to you.

## Modes

The mode sets the default for calls no rule covers.

| Mode | Behaviour |
| :- | :- |
| `default` | Reads run. Risky actions ask: deleting files, discarding git work, pushing, publishing, sudo, writing outside the project, sending data out. |
| `acceptEdits` | As `default`, and file edits run without asking. |
| `plan` | Only reading. The agent researches, then presents a plan with `present_plan` and stops. |
| `dontAsk` | Anything not pre-approved is refused instead of asked. Good for unattended runs. |
| `bypassPermissions` | Everything runs. Only inside a sandbox or a throwaway machine. |

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), permission_mode="acceptEdits")
```

With the SDK API, it is `AgentOptions(permission_mode="acceptEdits")`.

## Rules

Rules name the calls to allow, deny or ask about. They use the Claude Agent SDK's syntax:

| Rule | Covers |
| :- | :- |
| `Bash` | every bash call |
| `Bash(git status)` | that exact command |
| `Bash(npm run test:*)` | commands starting with `npm run test` |
| `Edit(src/**)` | writes under `src/`, by any file-writing tool |
| `Read(~/.ssh/**)` | reads under `~/.ssh` |
| `WebFetch(domain:example.com)` | fetches from `example.com` |
| `mcp__github__*` | every tool from the `github` MCP server |

```python
from shipit_agent import Agent, PermissionEngine
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(
    llm=build_llm_from_env(),
    permissions=PermissionEngine(
        allow=["Bash(pytest *)", "Bash(git diff *)"],
        deny=["Bash(git push *)", "Read(.env)"],
        ask=["Edit(migrations/**)"],
    ),
)
```

`allowed_tools=[...]` and `disallowed_tools=[...]` are shorthands for allow and deny rules. A bare tool name in `disallowed_tools` also hides the tool from the model.

**Order.** Hooks run first, then deny rules, ask rules, the mode, allow rules, and last your callback. A deny always wins.

**Compound commands** are judged part by part. A deny rule matches if any part matches; an allow rule only if every part does. `Bash(ls *)` does not approve `ls && rm -rf build`.

**Paths are normalised** before matching, so `src/../secrets` is not under `src/**`.

## Deciding in code

A callback decides the calls that would otherwise ask. Return a `PermissionResult`, or `None` to ask as usual.

```python
from shipit_agent import Agent, PermissionDecision, PermissionResult
from shipit_agent.llms import build_llm_from_env


def decide(tool_name: str, arguments: dict) -> PermissionResult | None:
    command = arguments.get("command", "")
    if tool_name == "bash" and command.startswith("rm "):
        return PermissionResult(PermissionDecision.DENY, reason="Deleting is done by a person.")
    if tool_name == "bash" and command.startswith("npm install"):
        return PermissionResult(PermissionDecision.ALLOW, scope="session")
    return None


agent = Agent.with_builtins(llm=build_llm_from_env(), permission_callback=decide)
```

`scope="session"` approves that exact call for the rest of the session. `updated_arguments` runs the call with changed arguments.

The SDK's `can_use_tool` is the same idea, with the SDK's types:

```python
from shipit_agent.sdk import AgentOptions, PermissionResultAllow, PermissionResultDeny


async def can_use_tool(tool_name, input_data, context):
    if tool_name == "bash" and "deploy" in input_data.get("command", ""):
        return PermissionResultDeny(message="No deploys from the agent.")
    return PermissionResultAllow(updated_input=input_data)


options = AgentOptions(can_use_tool=can_use_tool)
```

## What the model is told

A denied call is not run, and the model is told the decision is final: it should not retry or work around it, and it should say what was declined. A call that needs approval nobody can give (no callback, no queue) is reported the same way, with the instruction to finish the rest of the task and name what still needs approval.

## Approving later

For agents that run unattended, an `ApprovalQueue` parks risky calls instead of refusing them. A person reviews the queue, and approved calls run then.

```python
from shipit_agent import Agent, ApprovalQueue
from shipit_agent.llms import build_llm_from_env

queue = ApprovalQueue()
agent = Agent.with_builtins(llm=build_llm_from_env(), approvals=queue)
agent.run("Post the release notes to #eng.")

for action in queue.pending():
    print(action.tool, action.arguments)
queue.approve_all(by="rahul")
```

## See also

- [Hooks](hooks.md): run your own code before and after every tool call.
- [Sandbox](sandbox.md): let commands run without asking, inside an OS sandbox.
