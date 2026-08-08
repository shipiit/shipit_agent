# Triggers

An agent you have to ask is a tool. An agent that reacts is a colleague.
A trigger is the second thing: an email arrives, a webhook fires, a row
lands — and the agent runs.

```python
from shipit_agent import Agent, TriggerRegistry

agent = Agent(llm=llm, tools=tools)
triggers = TriggerRegistry()          # durable, on disk, by default

@triggers.on("gmail", description="Log every RSVP into the sheet")
def rsvp(event):
    if "rsvp" not in event.data.get("subject", "").lower():
        return None                   # not for me — a skip, not a failure
    return f"Log this RSVP into the guest sheet:\n\n{event.data['body']}"

# Your mail poller, webhook view or cron does exactly this:
triggers.fire("gmail", {"subject": "RSVP", "body": "Jordan will attend."})

# And a worker, anywhere, does this:
triggers.run_forever(agent, every=5)
```

## Firing is not running

`fire()` records the event and returns. Nothing runs until something
drains the queue.

This separation is the whole design rather than an implementation detail.
A webhook has to answer in milliseconds; an agent takes seconds. A sender
that times out waiting for you will deliver the same email again, and
again, and you will process it three times. So the two halves are split by
construction: receiving is fast and always succeeds, running happens
somewhere else.

```python
event_id = triggers.fire("stripe", payload)   # returns immediately
```

## The queue is durable by default

`SqliteTriggerQueue` writes to disk, and it is the default for one
reason: an event that arrives while no worker is running has to still be
there afterwards. Otherwise "runs on every email" is a promise that fails
quietly at 3am, in exactly the case it was bought for.

```python
from shipit_agent import SqliteTriggerQueue, TriggerRegistry

triggers = TriggerRegistry(queue=SqliteTriggerQueue("triggers.db"))
```

`InMemoryTriggerQueue` exists and is named that way so you have to mean
it. It is for tests.

## Delivered once, and it stops if it cannot be

Claiming an event takes the row, so two workers can drain the same queue
without both running it. A worker that dies mid-run has its claim expire
rather than stranding the event forever.

And an event that fails `max_attempts` times is dropped rather than
retried indefinitely — a poison event that can never succeed would
otherwise hide everything queued behind it.

```python
triggers = TriggerRegistry(max_attempts=3)
```

## Returning `None` is how a trigger filters

A handler that returns `None` skips the event. That is a normal outcome,
not an error: it is how "only RSVPs" and "only failed builds" are
expressed.

```python
@triggers.on("github")
def failed_builds(event):
    if event.data.get("conclusion") != "failure":
        return None
    return f"A build failed: {event.data['url']}. Say what broke."
```

The skip still consumes the event — it was handled, and the answer was
"nothing to do".

## A trigger builds a prompt, not an agent

Nothing here constructs an agent, loads credentials or picks a model. You
hand `drain()` the agent you already configured.

That is deliberate. A reactive path that builds its own agent is a second
set of credentials running unattended with nobody accountable for what it
does. Your agent, your permissions, your budget — the trigger only
decides *what to ask it*.

## Draining

Three ways, depending on what you have.

```python
# Once, from cron:
runs = triggers.drain(agent)

# Forever, in a worker:
triggers.run_forever(agent, every=5, stop=stop_event)

# In a batch:
from shipit_agent import fire_all
fire_all(triggers, "gmail", [msg1, msg2, msg3])
```

`run_forever` takes a `threading.Event` as `stop`, so a worker shuts down
cleanly rather than being killed.

## Seeing what is wired

```python
summary = triggers.summary()
# {"sources": ["gmail", "github"], "pending": 3, "triggers": [...]}
```

`pending` is the number of events waiting, which is the number to put
behind a "Live" badge — and the one to alert on if it stops going down.

## Each run reports itself

`drain()` returns one `TriggerRun` per trigger that ran:

```python
for run in triggers.drain(agent):
    print(run.trigger, run.ok, run.skipped, run.error)
```

Enough to render a status list without reaching into anything private.

## See also

- [Scheduled agents](scheduled-agents.md) — time-based rather than event-based
- [Sessions & memory](sessions.md) — where a reactive run's history lives
- [Streaming](streaming.md) — watching a triggered run as it happens
