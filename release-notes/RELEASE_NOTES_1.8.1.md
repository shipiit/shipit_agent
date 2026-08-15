# shipit-agent 1.8.1 — Ask first

Some tool calls should never fire without a human saying **yes** — deleting a
file, wiring money, sending an email. 1.8.1 makes that a one-line declaration on
the tool itself, and fixes the loop that made a refusal ask twice.

```python
from shipit_agent.tools import requires_confirmation

@requires_confirmation("Deletes files permanently — cannot be undone.",
                       impact="irreversible")
class DeleteTool: ...

# Confirm only when it matters — a cheap call runs free:
@requires_confirmation("Large transfer needs sign-off.",
                       when=lambda a: a["amount"] >= 10_000)
def wire_transfer(amount, to): ...
```

## A first-class tool confirmation

shipit already had a permission gate (allow / ask / deny) and an approval queue.
1.8.1 adds the ergonomic that makes HITL powerful: a tool declares *for itself*
when it needs approval, with `@requires_confirmation`, wired into the machinery
you already have.

It is more than a yes/no:

- **Conditional** — a `when(arguments)` predicate, so only the dangerous call pauses.
- **Impact levels** — `default` / `destructive` / `irreversible` for UI severity.
- **A per-tool floor** — `PermissionEngine.check` asks even under a bypass/allow
  mode, because the tool itself demands it. Only a hard deny outranks it.
- **Approve-with-edit** — the answer flows through the existing approval queue,
  so a human can approve *and* modify the arguments.
- **Fail-safe** — a broken predicate asks rather than silently skipping the gate.

Wire a `permission_callback(name, args) -> PermissionResult | None` into the
Agent and that callback *is* your human-in-the-loop — a console prompt, an
approval queue, or a card in your web UI.

## A denial is now final

Before 1.8.1, when a human declined a tool the model was told only that it "was
not run" — which it read as a transient failure and **retried**, re-prompting the
human on every loop. The denied result now says the decision is final — *do not
retry, rephrase, or pursue the goal another way; silence is not consent* — so a
run stops cleanly after one refusal. Fixed in both the sync and async runtimes.

## Try it

A runnable notebook ships under `notebooks/tool_confirmation/` — the gate on its
own, conditional confirmation, and a real agent that pauses on an HTML card while
**you** type `y` / `n`. It reads the provider key from a local, gitignored
`.env`, so nothing sensitive is ever committed.

## Compatibility

Fully backward-compatible. A tool without `@requires_confirmation` behaves exactly
as before; the decorator is opt-in per tool. The denied-result wording still
contains "was NOT run", so any existing checks keep passing.
