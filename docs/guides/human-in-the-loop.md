---
title: Human-in-the-loop
description: Make a tool ask a human before it runs with one decorator — @requires_confirmation. Conditional confirmation, impact levels, a per-tool floor no bypass can skip, and a denial the model can't retry.
---

# Human-in-the-loop

Some tool calls should never fire without a human saying **yes** — deleting a
file, wiring money, sending an email, running a migration. In shipit a tool
declares that for itself with one decorator, and the permission gate **pauses**
before it runs.

```python
from shipit_agent.tools import requires_confirmation

@requires_confirmation("Deletes a path permanently — cannot be undone.",
                       impact="irreversible")
class DeleteTool:
    name = "delete_path"
    ...
```

That's the whole change. Any agent holding a confirmed tool will pause for
approval before calling it — no policy file, no per-agent wiring.

## The decorator

Three call styles, all equivalent for the message:

```text
@requires_confirmation                              # bare — always confirm
@requires_confirmation("why this is dangerous")     # positional message
@requires_confirmation(message="…", impact="…", when=…)   # keyword
```

### Confirm only when it matters

A `when(arguments)` predicate makes confirmation **conditional** — a cheap call
runs free and only the dangerous one pauses:

```python
@requires_confirmation(
    "Large wire transfer needs sign-off.",
    impact="irreversible",
    when=lambda args: args.get("amount", 0) >= 10_000,
)
def wire_transfer(amount: float, to: str) -> str:
    ...
```

A `$5` transfer runs; a `$50,000` transfer asks. A broken predicate **fails
safe** — it asks rather than silently skipping the gate.

### Impact levels

`impact` ∈ `default` · `destructive` · `irreversible`, so a UI can colour the
approval card by severity. It's metadata for your surface — shipit doesn't treat
`irreversible` differently from `destructive`; *you* decide how to render each.

## The human surface — `permission_callback`

Wire a callback into the agent, and that callback **is** your human-in-the-loop:

```python
from shipit_agent import Agent
from shipit_agent.permissions import PermissionResult, PermissionDecision

def human_approval(name, args):
    # A console prompt, an approval queue, or a card in your web UI.
    answer = input(f"Approve {name}({args})?  [y]es / [n]o: ")
    if answer.strip().lower() in ("y", "yes"):
        return PermissionResult(PermissionDecision.ALLOW, reason="approved")
    return PermissionResult(PermissionDecision.DENY, reason="declined")

agent = Agent(llm=llm, tools=[DeleteTool()], permission_callback=human_approval)
agent.run("Delete /tmp/old_report.pdf using delete_path.")
```

Return `ALLOW`, `DENY` (optionally with **edited arguments** in
`updated_arguments`), or `None` to defer to the rest of the policy. In a web app
your callback pushes the request to the UI and awaits the click through shipit's
async approval queue.

## How the gate decides

Before a tool runs, `PermissionEngine.check(name, args, tool)` evaluates, in
order:

| Rank | Rule |
| --- | --- |
| 1 | **Hard deny** — always wins |
| 2 | **`@requires_confirmation`** — a per-tool **floor**: asks even under a bypass/allow mode |
| 3 | Mode (`bypass` / `plan` / `acceptEdits`) |
| 4 | Explicit `allow` / `ask` rules, then your callback |

Because confirmation sits above the mode logic, **no session setting can silently
skip a tool that demands a human yes** — only an explicit deny outranks it.

## A denial is final

When a human declines, the model is told the decision is **final** — *do not
retry, rephrase, or pursue the goal another way; silence is not consent.* So a
run **stops after one refusal** instead of re-prompting on every loop. You never
see the same confirmation twice for one declined call.

## Try it

A runnable notebook ships under `notebooks/tool_confirmation/` — the gate on its
own, conditional confirmation, and a real agent that pauses on an HTML card while
**you** type `y` / `n`.

## See also

- [Permissions, plan mode & hooks](../guides/permissions.md) — the full permission
  model the confirmation floor plugs into.
- [Hooks & middleware](hooks.md) — `before_tool` hooks that can deny or rewrite a
  call programmatically.
