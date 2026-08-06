# shipit-agent 1.3.0 — Triggers

An agent you have to ask is a tool. An agent that reacts is a colleague.

1.2.0 made a run *visible*. This release makes one *start on its own*: an
email lands, a webhook fires, a row appears — and the agent runs.

```python
from shipit_agent import Agent, TriggerRegistry

agent = Agent(llm=llm, tools=[...])
triggers = TriggerRegistry()          # durable, on disk, by default

@triggers.on("gmail", description="Log every RSVP into the sheet")
def rsvp(event):
    if "rsvp" not in event.data.get("subject", "").lower():
        return None                   # not for me — a skip, not a failure
    return f"Log this RSVP into the guest sheet:\n\n{event.data['body']}"

# Your mail poller, webhook view, or cron does exactly this:
triggers.fire("gmail", {"subject": "RSVP", "body": "Jordan will attend."})

# And a worker, anywhere, does this:
triggers.run_forever(agent, every=5)
```

## Four decisions worth knowing

**Firing is not running.** `fire()` records the event and returns. Nothing
runs until something drains. A webhook has to answer in milliseconds, an
agent takes seconds, and a sender that times out delivers the same email
again — so the two are separate by construction, not by convention.

**The queue is durable by default.** `SqliteTriggerQueue` writes to disk.
An event that arrives while no worker is running has to still be there
afterwards, or "runs on every email" is a promise that fails quietly at 3am,
in the one case it was bought for. `InMemoryTriggerQueue` exists, and is
named that way so you have to mean it.

**An event is delivered once, and stops if it can't be.** Claiming takes the
row, so two workers can drain the same queue without both running the same
event; an abandoned claim expires so a crashed worker doesn't strand it. And
an event that fails `max_attempts` times is dropped rather than retried
forever — a poison event that never succeeds otherwise hides everything
queued behind it.

**A trigger builds a prompt, not an agent.** Nothing here constructs an
agent, loads credentials, or picks a model. You hand `drain()` the agent you
already configured. A reactive path that builds its own agent is a second
set of credentials running unattended with nobody accountable for it.

## The rest of the surface

| | |
|---|---|
| `registry.on(source, name=…, description=…)` | Register by decorator |
| `registry.register(Trigger(...))` | Register explicitly |
| `registry.fire(source, data)` → `event_id` | Record; runs nothing |
| `fire_all(registry, source, [data, …])` | A batch |
| `registry.drain(agent, limit=10)` → `[TriggerRun]` | Run what's queued |
| `registry.run_forever(agent, every=5, stop=…)` | The worker, stoppable |
| `registry.summary()` | What's wired, what's waiting |

`TriggerRun` carries `trigger`, `ok`, `skipped`, `output`, `error` — enough
to render a status list without inspecting anything private.

## Upgrading

Nothing changed underneath you. `pip install -U shipit-agent`; existing code
runs untouched.

---

3,104 tests, all passing.
