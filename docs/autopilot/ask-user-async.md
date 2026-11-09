---
title: ask_user_async — non-blocking mid-run clarifications
description: Pause an Autopilot run to ask the user a question without blocking the loop. Autopilot halts cleanly into `awaiting_user`; the user answers via CLI; resume picks up where it left off.
---

# `ask_user_async` — non-blocking clarifications

Long-running Autopilot jobs often need a clarification mid-run: "Which
region?", "Okta or Auth0?", "Do you want the migration applied now?".
A classic `ask_user` tool **blocks the loop** — fine for a 5-minute
run, useless for an overnight one.

`ask_user_async` solves that with a **file-based side channel**:

1. The tool writes the question to
   `~/.shipit_agent/askuser/<run_id>.json`.
2. Autopilot checkpoints and halts with `status="awaiting_user"`.
3. The user answers at their own pace —
   `shipit answer <run_id> "..."`.
4. Autopilot `resume()` picks up the answer and keeps going.

> **TL;DR** — `tools=[AskUserAsyncTool()]` on your Autopilot and an
> `ask_user_async(question=...)` call makes the run park cleanly. The
> user's answer on the `shipit answer <run_id>` CLI is durable; resume
> is automatic.

---

## Quick start

```python
from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep import Goal
from shipit_agent.tools.ask_user_async import AskUserAsyncTool

autopilot = Autopilot(
    llm=llm,
    goal=Goal(
        objective="Configure the deployment target.",
        success_criteria=["Provider chosen", "Region chosen"],
    ),
    budget=BudgetPolicy(max_iterations=6),
    tools=[AskUserAsyncTool()],
)
result = autopilot.run(run_id="deploy-config")
print(result.status)        # "awaiting_user" when a question was queued
print(result.halt_reason)   # "awaiting user answer (ask_user_async)"
```

The model invokes the tool like any other:

```python
ask_user_async(
    question="Which cloud provider should I target — AWS, GCP, or Azure?",
    context="No cloud config in the repo yet; a choice is required.",
    choices=["AWS", "GCP", "Azure"],   # optional — user not forced to pick one
)
```

---

## Answering

### From the CLI

```bash
shipit answer deploy-config "AWS"
```

That's it. The next time Autopilot resumes `deploy-config`, the
question is answered and the loop continues — the model sees your reply
as tool output and proceeds.

Inspect without answering:

```bash
$ shipit answer deploy-config
[00] PENDING   Which cloud provider should I target — AWS, GCP, or Azure?
          context: No cloud config in the repo yet; a choice is required.
          choices: AWS, GCP, Azure
```

### Programmatically

```python
from shipit_agent.askuser_channel import write_answer

write_answer("deploy-config", "AWS")
```

Multiple outstanding questions? Target a specific one:

```python
write_answer("deploy-config", "us-east-1", index=1)   # answers the second Q
```

---

## Autopilot integration

`Autopilot.run()` and `Autopilot.resume()` both check the ask-user
channel after every iteration:

- Any pending question → halt with `status="awaiting_user"`.
- `resume()` on a run whose question is still pending → return
  immediately (don't burn an iteration re-asking).
- `resume()` after the user answered → proceed normally.

Status rollup:

| Status | Meaning |
| --- | --- |
| `awaiting_user` | At least one question is pending |
| `completed` / `partial` / `halted` / `failed` | Standard Autopilot statuses (see [Autopilot overview](index.md)) |

---

## Side-channel anatomy

```
~/.shipit_agent/askuser/<run_id>.json
```

```json
{
  "run_id": "deploy-config",
  "entries": [
    {
      "question": "Which cloud provider…",
      "asked_at": 1713710400.0,
      "context": "No cloud config in the repo yet.",
      "choices": ["AWS", "GCP", "Azure"],
      "answer": null,
      "answered_at": null
    }
  ]
}
```

Atomic rename on every write — a crash during save never corrupts the
channel.

Redirect via `SHIPIT_ASKUSER_DIR=/custom/path` env for tests or
containerised runs.

---

## CLI reference

| Command | Effect |
| --- | --- |
| `shipit answer <run_id> "<text>"` | Answer the latest pending question |
| `shipit answer <run_id> "<text>" --index N` | Answer the N-th question (zero-based) |
| `shipit answer <run_id>` | Show pending + answered history without changing anything |

---

## Design rules for prompts

Good `ask_user_async` prompts:

- **One focused question** — bundle alternatives in parens if needed.
- **Short context** — 1-2 sentences on *why* the choice matters.
- **Concrete choices when applicable** — "Options: Okta, Auth0, Google Workspace" beats "what auth do you want?".

Bad (tell your model to avoid these):

- "Should I proceed?" — pick a default and proceed.
- "Is this correct?" after a trivial step — don't pause on routine work.
- "What's your preference on the architecture?" — the research comes first; ask only after options are concrete.

---

## Notebook

- `notebooks/45_cost_router_async_ask_vision_sandbox.ipynb` — live round-trip including the channel inspection.
