---
title: Scheduler daemon — 24-hour operation
description: A persistent goal queue on disk, drained tick-by-tick until SIGINT. Pair with systemd/launchd/Docker to turn any machine into an always-on Autopilot host.
---

# Scheduler daemon — 24-hour operation

`SchedulerDaemon` is the thing you run when you want shipit_agent to
keep working overnight — or for weeks. It maintains a **persistent
JSON queue of goals** and drains them one at a time through Autopilot,
emitting heartbeat events so you know it's alive.

> **TL;DR** — `shipit queue add my-goal "..."` then `shipit daemon` and
> walk away. Or `SchedulerDaemon(llm_factory=lambda: llm).run_forever()`
> from Python.

---

## Architecture

```
                ~/.shipit_agent/autopilot-queue.json
                             │
                             ▼
   ┌─────────────────────────────────────────────────┐
   │  SchedulerDaemon.run_forever()                  │
   │                                                  │
   │   tick ▶ run_once() ▶ Autopilot(next_pending)   │
   │       │                  │                       │
   │       │                  ├─ checkpoints.json      │
   │       │                  ├─ stream events         │
   │       │                  └─ artifacts             │
   │       │                                          │
   │       └─ heartbeat every N idle ticks             │
   └─────────────────────────────────────────────────┘
```

Queue state lives on disk; the daemon process is **stateless**.
Crash → restart → resume from exactly where you left off.

---

## CLI — the fast path

```bash
# Add a goal
shipit queue add nightly-lint "Summarise every ERROR in today's build.log" \
    --criteria "Per-file counts reported" \
    --criteria "Top 3 noisiest files listed" \
    --max-seconds 600 --max-tools 50

# List
shipit queue list

# Remove
shipit queue remove nightly-lint

# Drain one pending goal and exit (good for cron)
shipit daemon --once

# Run forever
shipit daemon --tick 5
```

The CLI reads `SHIPIT_LLM=<bedrock|openai|...>` from env. Default is
Bedrock Llama 4 Scout — no extra arguments needed if your AWS creds
are wired.

---

## Python API

```python
from shipit_agent.scheduler_daemon import SchedulerDaemon

# `llm_factory` builds a fresh LLM per run — important for long
# daemons where provider tokens / credentials may rotate.
daemon = SchedulerDaemon(llm_factory=lambda: llm, tick_seconds=5)

# Enqueue
daemon.enqueue(
    run_id="nightly-review",
    objective="Review PRs merged in the last 24h, flag security regressions.",
    success_criteria=[
        "No high-severity finding in last 24h",
        "Summary of merged PRs",
    ],
    budget={"max_seconds": 1800, "max_tool_calls": 150},
)

# Query
for entry in daemon.list_queue():
    print(entry.run_id, entry.status, entry.objective[:60])

# Remove
daemon.remove("nightly-review")
```

---

## Queue entry lifecycle

A queued goal transitions through these statuses:

```
  pending  ──▶  running  ──▶  done
                    │
                    └───────▶  halted   (budget tripped before any criterion verified)
                    │
                    └───────▶  failed   (inner exception)
```

Completed entries stay in the queue until you remove them, so you can
inspect `entry.result` — the full `AutopilotResult.to_dict()` — after
the fact.

---

## Running it forever

```python
daemon.run_forever()                       # blocks; installs SIGINT/SIGTERM handlers
```

- Sleeps `tick_seconds` between scans (default 5s).
- Picks the earliest `pending` entry each tick.
- Fires `on_heartbeat` every `heartbeat_every_ticks` (default 60) idle ticks.
- Shuts down cleanly on SIGINT or SIGTERM.

### Heartbeat payload

```python
{
    "kind": "daemon_heartbeat",
    "tick": 347,
    "idle_ticks": 60,
    "pending": 2,
    "total": 5,
    "queue_path": "/Users/you/.shipit_agent/autopilot-queue.json",
}
```

Wire to Slack / Datadog / custom webhook:

```python
def to_slack(payload):
    if payload.get("pending", 0) == 0:
        return                             # nothing to report
    notify_slack(f"Autopilot daemon: {payload['pending']} pending jobs")

daemon = SchedulerDaemon(
    llm_factory=llm_factory,
    on_heartbeat=to_slack,
    heartbeat_every_ticks=12,              # ~1 min at 5s tick
)
```

---

## Running under a supervisor

### systemd

```ini
# /etc/systemd/system/shipit-agent.service
[Unit]
Description=shipit_agent scheduler daemon
After=network-online.target

[Service]
Type=simple
User=shipit
ExecStart=/usr/local/bin/shipit daemon --tick 10
Restart=on-failure
RestartSec=15
Environment=SHIPIT_LLM=bedrock
Environment=AWS_REGION=us-east-1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shipit-agent
journalctl -u shipit-agent -f
```

### launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/dev.shipit.daemon.plist -->
<plist version="1.0"><dict>
  <key>Label</key>     <string>dev.shipit.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/shipit</string>
    <string>daemon</string>
    <string>--tick</string><string>10</string>
  </array>
  <key>RunAtLoad</key>  <true/>
  <key>KeepAlive</key>  <true/>
  <key>StandardOutPath</key> <string>/tmp/shipit-daemon.log</string>
  <key>StandardErrorPath</key> <string>/tmp/shipit-daemon.err</string>
</dict></plist>
```

```bash
launchctl load -w ~/Library/LaunchAgents/dev.shipit.daemon.plist
tail -F /tmp/shipit-daemon.log
```

### Docker

```dockerfile
FROM python:3.11-slim
RUN pip install shipit-agent[bedrock]
ENV SHIPIT_LLM=bedrock
CMD ["shipit", "daemon", "--tick", "10"]
```

---

## Queue file format

`~/.shipit_agent/autopilot-queue.json` is a plain JSON array; external
tools can enqueue by appending an entry and the daemon will pick it up
on the next tick.

```json
[
  {
    "run_id": "nightly-review",
    "objective": "Review PRs merged in the last 24h",
    "success_criteria": ["No high-severity finding", "Summary present"],
    "budget": {"max_seconds": 1800},
    "status": "pending",
    "created_at": 1713710400.0,
    "started_at": null,
    "finished_at": null,
    "result": null
  }
]
```

---

## API reference

```python
class SchedulerDaemon:
    def __init__(
        self, *,
        llm_factory: Callable[[], LLM],
        queue_path: str | Path | None = None,
        tick_seconds: float = 5.0,
        heartbeat_every_ticks: int = 60,
        on_heartbeat: Callable[[dict], None] | None = None,
        tools: list[Tool] | None = None,
        mcps: list[MCPServer] | None = None,
        checkpoint_dir: str | Path | None = None,
    ) -> None: ...

    def enqueue(self, *, run_id, objective, success_criteria=None, budget=None) -> QueueEntry: ...
    def list_queue(self) -> list[QueueEntry]: ...
    def remove(self, run_id: str) -> bool: ...
    def run_once(self) -> AutopilotResult | None: ...
    def run_forever(self) -> None: ...
```

---

## Notebook

- `notebooks/39_persistence_and_scheduler_daemon.ipynb` — end-to-end walkthrough, including crash/resume + queue operations.
