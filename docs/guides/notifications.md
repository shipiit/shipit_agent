# Notification Hub

Send agent lifecycle events to Slack, Discord, and Telegram. Multi-channel dispatch with severity filtering, custom templates, and automatic hook integration.

## Setup — Getting your webhook URLs

Before using notifications, you need credentials for each channel. Add them to your `.env` file:

```bash
# .env
# Slack — Create at https://api.slack.com/messaging/webhooks
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...

# Discord — Server Settings → Integrations → Webhooks → New Webhook → Copy URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456789/abcdefghijklmnop

# Telegram — Message @BotFather → /newbot → copy token, then get chat_id
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
```

### How to get each credential

**Slack Webhook:**

1. Go to [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks)
2. Click **Create your Slack app** → pick a workspace
3. Under **Incoming Webhooks** → toggle **On**
4. Click **Add New Webhook to Workspace** → select a channel
5. Copy the webhook URL

**Discord Webhook:**

1. Open your Discord server
2. Go to **Server Settings** → **Integrations** → **Webhooks**
3. Click **New Webhook** → name it "ShipIt Agent"
4. Select the target channel → click **Copy Webhook URL**

**Telegram Bot:**

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` → follow prompts → copy the **bot token**
3. Add the bot to your group/channel
4. Get your chat ID: send a message in the group, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and find `"chat":{"id":...}`

## Quick start

```python
from shipit_agent import Agent
from shipit_agent.notifications import SlackNotifier, NotificationManager

slack = SlackNotifier(webhook_url="https://hooks.slack.com/services/T.../B.../xxx")
manager = NotificationManager([slack])

agent = Agent.with_builtins(llm=llm, hooks=manager.as_hooks("my-agent"))
result = agent.run("Analyze the codebase")
# Slack receives: "my-agent started", "my-agent completed in 12.3s"
```

### Production wiring with `.env`

```python
import os
from dotenv import load_dotenv
from shipit_agent import Agent
from shipit_agent.notifications import (
    NotificationManager, SlackNotifier, DiscordNotifier, TelegramNotifier,
)
from shipit_agent.costs import CostTracker, Budget

load_dotenv()

# Build notifiers from environment variables
notifiers = []
if os.getenv("SLACK_WEBHOOK_URL"):
    notifiers.append(SlackNotifier(webhook_url=os.environ["SLACK_WEBHOOK_URL"]))
if os.getenv("DISCORD_WEBHOOK_URL"):
    notifiers.append(DiscordNotifier(webhook_url=os.environ["DISCORD_WEBHOOK_URL"]))
if os.getenv("TELEGRAM_BOT_TOKEN"):
    notifiers.append(TelegramNotifier(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
    ))

manager = NotificationManager(
    notifiers=notifiers,
    min_severity="info",            # only info+ gets sent
    events=["run_completed", "tool_failed", "cost_alert"],  # filter events
)

# Cost tracker with budget alert
tracker = CostTracker(budget=Budget(max_dollars=5.00, warn_at=0.80))

# Wire everything into the agent
agent = Agent.with_builtins(
    llm=llm,
    prompt="You are a security auditor.",
    hooks=manager.as_hooks("security-auditor"),
)

result = agent.run("Audit the authentication module")
# Slack/Discord/Telegram all receive status updates automatically
```

## Notification data model

Every notification flowing through the system is a `Notification` dataclass.

```python
from shipit_agent.notifications import Notification

note = Notification(
    event="run_completed",
    title="researcher -- Run Completed",
    message="researcher completed in 4.2s | Cost: 1832 tokens",
    severity="info",
    metadata={"agent": "researcher", "duration": "4.2s", "cost": "1832 tokens"},
)
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | `str` | Lifecycle event name (`run_started`, `run_completed`, `tool_failed`, `cost_alert`, `checkpoint_saved`) |
| `title` | `str` | Short human-readable title |
| `message` | `str` | Detailed message body with context |
| `severity` | `str` | One of `info`, `warning`, `error`, `critical` |
| `metadata` | `dict` | Arbitrary key-value pairs (agent name, duration, cost, tool name) |
| `timestamp` | `datetime` | UTC timestamp (auto-set on creation) |

```python
# Serialize for logging or storage
d = note.to_dict()
```

## Severity levels

Notifications are ordered by severity. Use `min_severity` on the manager to filter out low-priority noise.

| Level | Value | Use case |
|-------|-------|----------|
| `info` | 0 | Run started, task completed, checkpoints |
| `warning` | 1 | Budget threshold crossed, slow tasks |
| `error` | 2 | Tool failures, task errors |
| `critical` | 3 | Budget exceeded, unrecoverable failures |

## SlackNotifier

Sends notifications via Slack Incoming Webhooks using Block Kit for rich formatting. No external dependencies -- uses `urllib.request` directly.

```python
from shipit_agent.notifications import SlackNotifier

slack = SlackNotifier(
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
    channel="#agent-alerts",    # optional channel override (legacy webhooks only)
    username="ShipIt Agent",   # bot display name
)
```

Block Kit layout for each notification:

1. **Header block** with the notification title
2. **Section block** with the message body (mrkdwn)
3. **Fields section** with metadata key-value pairs (two-column grid)
4. **Context block** with timestamp and severity

Severity is colour-coded via the attachment sidebar:

| Severity | Colour |
|----------|--------|
| `info` | Blue (`#3498db`) |
| `warning` | Yellow (`#f1c40f`) |
| `error` | Red (`#e74c3c`) |
| `critical` | Dark red (`#992d22`) |

```python
# Synchronous send (no event loop needed)
slack.send_sync(note)

# Async send (inside an async context)
ok = await slack.send(note)

# Batch send
results = await slack.send_batch([note1, note2, note3])
```

## DiscordNotifier

Sends notifications via Discord Webhooks using embedded messages with colour-coded severity.

```python
from shipit_agent.notifications import DiscordNotifier

discord = DiscordNotifier(
    webhook_url="https://discord.com/api/webhooks/123/abc...",
    username="ShipIt Agent",
    avatar_url="https://example.com/bot-avatar.png",  # optional
)
```

Each notification becomes a Discord embed with:

- Title and description from the notification
- Colour bar mapped from severity
- Inline fields for each metadata entry
- Footer with severity and ISO timestamp

Discord returns `204 No Content` on success, which the notifier handles correctly.

```python
ok = await discord.send(note)
discord.send_sync(note)
```

## TelegramNotifier

Sends notifications via the Telegram Bot API using MarkdownV2 formatting. Special characters are escaped automatically.

```python
from shipit_agent.notifications import TelegramNotifier

telegram = TelegramNotifier(
    bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    chat_id="-1001234567890",
)
```

Message format:

```
<emoji> *Title*
--------------------
Message body

*key:* value
*key:* value

_2026-04-13 14:30:00 UTC | info_
```

Severity emojis: info, warning, error, critical (mapped to standard Unicode emoji).

```python
ok = await telegram.send(note)
telegram.send_sync(note)
```

## NotificationManager

The central dispatcher that sends notifications to multiple channels simultaneously.

```python
from shipit_agent.notifications import (
    NotificationManager,
    SlackNotifier,
    DiscordNotifier,
    TelegramNotifier,
)

manager = NotificationManager(
    notifiers=[
        SlackNotifier(webhook_url="https://hooks.slack.com/..."),
        DiscordNotifier(webhook_url="https://discord.com/api/webhooks/..."),
        TelegramNotifier(bot_token="...", chat_id="..."),
    ],
    min_severity="info",     # minimum severity to dispatch
    events=None,             # None = all events; or ["run_completed", "tool_failed"]
)
```

### Sending manually

```python
from shipit_agent.notifications import Notification

note = Notification(
    event="deployment",
    title="Deployment Complete",
    message="v2.1.0 deployed to production",
    severity="info",
    metadata={"version": "2.1.0", "env": "production"},
)

# Async
results = await manager.notify(note)
# {"slack": True, "discord": True, "telegram": False}

# Sync (creates event loop if needed, safe from any context)
results = manager.notify_sync(note)
```

### Auto-hooking with as_hooks()

Wire the manager into an agent's lifecycle with a single call.

```python
hooks = manager.as_hooks(agent_name="researcher")
agent = Agent.with_builtins(llm=llm, hooks=hooks)
```

Events automatically emitted:

| Hook | Event | Severity |
|------|-------|----------|
| `on_before_llm` (first call) | `run_started` | `info` |
| `on_after_llm` | `run_completed` | `info` |
| `on_after_tool` (on failure) | `tool_failed` | `error` |

## Severity and event filtering

### Severity filter

Only dispatch notifications at or above a minimum severity.

```python
# Only errors and critical -- skip info and warning
manager = NotificationManager(
    notifiers=[slack],
    min_severity="error",
)
```

### Event filter

Only dispatch specific event types.

```python
# Only notify on failures and cost alerts
manager = NotificationManager(
    notifiers=[slack],
    events=["tool_failed", "cost_alert"],
)
```

Both filters can be combined. A notification must pass both the event filter and the severity filter to be dispatched.

## Custom templates

Override the default message templates for any event.

```python
manager = NotificationManager(
    notifiers=[slack],
    templates={
        "run_started": "Agent `{agent}` is starting: {prompt_preview}",
        "run_completed": "Agent `{agent}` finished in {duration}. Cost: {cost}",
        "tool_failed": "ALERT: `{agent}` tool `{tool}` failed -- {error}",
        "cost_alert": "BUDGET: {agent} spent {spent} of {budget} ({percent}%)",
    },
)
```

Default templates:

| Event | Template |
|-------|----------|
| `run_started` | `{agent} started: {prompt_preview}` |
| `run_completed` | `{agent} completed in {duration} \| Cost: {cost} \| {output_preview}` |
| `tool_failed` | `{agent} tool '{tool}' failed: {error}` |
| `cost_alert` | `{agent} has spent {spent} of {budget} budget ({percent}%)` |
| `checkpoint_saved` | `{agent} checkpoint #{step} saved` |
| `crew_started` | `Crew '{crew}' started with {agent_count} agents, {task_count} tasks` |
| `crew_completed` | `Crew '{crew}' completed in {duration} \| {completed}/{total} tasks succeeded` |

Missing template variables are left as-is (no `KeyError`). The `render_template` function uses a safe format map internally.

## Combining with CostTracker for budget alerts

Send a Slack notification when the agent crosses 80% of its budget.

```python
from shipit_agent.costs import CostTracker, Budget
from shipit_agent.notifications import NotificationManager, SlackNotifier, Notification

slack = SlackNotifier(webhook_url="https://hooks.slack.com/...")
manager = NotificationManager([slack], min_severity="warning")

def on_budget_warning(spent: float, limit: float) -> None:
    note = Notification(
        event="cost_alert",
        title="Budget Warning",
        message=f"Agent has spent ${spent:.2f} of ${limit:.2f} budget",
        severity="warning",
        metadata={"spent": f"${spent:.2f}", "budget": f"${limit:.2f}"},
    )
    manager.notify_sync(note)

tracker = CostTracker(
    budget=Budget(max_dollars=5.00, warn_at=0.80),
    on_cost_alert=on_budget_warning,
)

agent = Agent.with_builtins(llm=llm, hooks=tracker.as_hooks())
```

## Full production wiring

```python
from shipit_agent import Agent
from shipit_agent.costs import CostTracker, Budget
from shipit_agent.notifications import (
    NotificationManager,
    SlackNotifier,
    DiscordNotifier,
    Notification,
)

# Channels
slack = SlackNotifier(
    webhook_url=os.environ["SLACK_WEBHOOK"],
    username="Production Agent",
)
discord = DiscordNotifier(
    webhook_url=os.environ["DISCORD_WEBHOOK"],
)

# Manager: only errors+ to Discord, everything to Slack
slack_mgr = NotificationManager([slack], min_severity="info")
discord_mgr = NotificationManager([discord], min_severity="error")

# Cost tracking with budget alert -> Slack
def alert(spent, limit):
    slack_mgr.notify_sync(Notification(
        event="cost_alert",
        title="Budget Alert",
        message=f"${spent:.2f} of ${limit:.2f}",
        severity="warning",
    ))

tracker = CostTracker(
    budget=Budget(max_dollars=10.00, warn_at=0.80),
    on_cost_alert=alert,
)

# Merge hooks from both systems
agent = Agent.with_builtins(
    llm=llm,
    hooks=slack_mgr.as_hooks("prod-agent"),
)

result = agent.run("Analyze production logs for anomalies")
print(f"Cost: ${tracker.total_cost:.4f}")
```

## Using with plain Agent (no builtins)

```python
from shipit_agent import Agent

slack = SlackNotifier(webhook_url="https://hooks.slack.com/...")
manager = NotificationManager([slack])

# Plain Agent — no built-in tools
agent = Agent(
    llm=llm,
    prompt="You analyze code quality.",
    hooks=manager.as_hooks("code-analyzer"),
)

result = agent.run("What are common Python anti-patterns?")
# Slack gets: "code-analyzer started" and "code-analyzer completed"
```

## Using with DeepAgent

```python
from shipit_agent.deep import DeepAgent

manager = NotificationManager([slack, discord])

deep = DeepAgent.with_builtins(
    llm=llm,
    verify=True,
    reflect=True,
    hooks=manager.as_hooks("deep-researcher"),
)

# Streaming with notifications — events are sent to Slack/Discord
# while you also get them locally
for event in deep.stream("Research AI safety frameworks"):
    print(f"[{event.type}] {event.message[:80]}")
```

## Using with ShipCrew

```python
from shipit_agent.deep.ship_crew import ShipCrew, ShipAgent, ShipTask

# Wire notifications into crew agents
researcher = ShipAgent(
    name="researcher",
    agent=Agent(llm=llm, prompt="You research.", hooks=manager.as_hooks("researcher")),
    role="Researcher",
)

writer = ShipAgent(
    name="writer",
    agent=Agent(llm=llm, prompt="You write.", hooks=manager.as_hooks("writer")),
    role="Writer",
)

crew = ShipCrew(
    name="notified-crew",
    coordinator_llm=llm,
    agents=[researcher, writer],
    tasks=[
        ShipTask(name="research", description="Research {topic}", agent="researcher", output_key="findings"),
        ShipTask(name="write", description="Write about {findings}", agent="writer", depends_on=["research"]),
    ],
)

# Every agent in the crew sends notifications independently
result = crew.run(topic="microservices patterns")
```

## Notifier protocol

Build custom notifiers by implementing the `Notifier` protocol.

```python
from shipit_agent.notifications.base import Notification, Notifier

class PagerDutyNotifier:
    name: str = "pagerduty"

    async def send(self, notification: Notification) -> bool:
        # POST to PagerDuty Events API v2
        ...
        return True

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
        return [await self.send(n) for n in notifications]
```

## API reference

| Class / Method | Description |
|----------------|-------------|
| `Notification(event, title, message, severity, metadata)` | Core notification dataclass |
| `notification.to_dict()` | Serialize to plain dict |
| `SlackNotifier(webhook_url, channel, username)` | Slack via Incoming Webhook + Block Kit |
| `DiscordNotifier(webhook_url, username, avatar_url)` | Discord via Webhook + embeds |
| `TelegramNotifier(bot_token, chat_id)` | Telegram via Bot API + MarkdownV2 |
| `notifier.send(notification)` | Async send, returns `bool` |
| `notifier.send_sync(notification)` | Blocking send, returns `bool` |
| `notifier.send_batch(notifications)` | Async batch send, returns `list[bool]` |
| `NotificationManager(notifiers, templates, min_severity, events)` | Multi-channel dispatcher |
| `manager.notify(notification)` | Async dispatch to all channels, returns `dict[str, bool]` |
| `manager.notify_sync(notification)` | Sync dispatch (safe from any context) |
| `manager.as_hooks(agent_name)` | Create `AgentHooks` for automatic lifecycle notifications |
| `render_template(template, **kwargs)` | Safe string formatting (missing keys left as-is) |
| `SEVERITY_ORDER` | Dict mapping severity names to int levels |
| `DEFAULT_TEMPLATES` | Dict of default event templates |
