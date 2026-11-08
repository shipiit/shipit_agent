---
title: Autopilot CLI
description: The `shipit` CLI surface — `autopilot`, `daemon`, and `queue` subcommands for long-running, daemon-hosted, and queue-managed operation.
---

# Autopilot CLI

Every Autopilot feature is reachable from the `shipit` CLI — the
Python API's twin, shaped for operators and supervisors.

```bash
shipit autopilot "<objective>"           # one-shot long run
shipit daemon                            # persistent queue drainer
shipit queue   {add,list,remove}         # queue management
shipit run     "<prompt>"                # short one-shot Agent (pre-existing)
shipit chat                              # interactive REPL (pre-existing)
```

---

## `shipit autopilot`

Run a single goal under Autopilot with streaming output.

```bash
shipit autopilot "Migrate every SQL call in src/ to parameterized form" \
    --criteria "No raw string concat in .sql calls" \
    --criteria "All tests pass" \
    --max-hours 4 \
    --max-tools 500 \
    --format tui
```

### Options

| Flag | Default | Notes |
| --- | --- | --- |
| `--criteria <text>` | empty | Repeat for each success criterion |
| `--run-id <id>` | `run-<epoch>` | Stable id for checkpoint + resume |
| `--resume` | off | Continue the given `--run-id` from its checkpoint |
| `--max-hours <h>` | budget default | Wall-clock cap |
| `--max-tools <n>` | budget default | Tool-call cap |
| `--max-tokens <n>` | budget default | Token cap |
| `--max-dollars <n>` | budget default | Dollar cap |
| `--heartbeat <sec>` | `60` | Heartbeat interval |
| `--format` | `tui` | `tui`, `jsonl`, or `plain` |
| `--checkpoint-dir <path>` | `~/.shipit_agent/checkpoints` | Where to store state |

### Resume

```bash
shipit autopilot --resume --run-id migrate-sql
```

Reads the checkpoint, builds an Autopilot with the original goal, and
keeps iterating. Budget counters (tokens, tool calls, iterations) continue
from where they left off.

---

## `shipit daemon`

Run the scheduler daemon in the foreground, draining pending goals
until SIGINT / SIGTERM.

```bash
shipit daemon                 # tick=5s, default queue
shipit daemon --tick 10 --queue /var/lib/shipit/queue.json
shipit daemon --once          # drain one pending goal and exit (cron-friendly)
```

### Operator tip

Pair with a process supervisor — see
[Scheduler daemon](scheduler-daemon.md#running-under-a-supervisor) for
systemd, launchd, and Docker recipes.

---

## `shipit queue`

Manage the persistent goal queue from the command line.

```bash
# Add a goal
shipit queue add nightly-review "Summarise today's PRs" \
    --criteria "Mentions every merged PR" \
    --max-seconds 1800 \
    --max-tools 150

# List
shipit queue list

# Remove
shipit queue remove nightly-review
```

### `queue add` options

| Flag | Notes |
| --- | --- |
| `--criteria <text>` | Repeat for each criterion |
| `--max-seconds <n>` | Wall-clock cap for this goal |
| `--max-tools <n>` | Tool-call cap for this goal |

The daemon picks the earliest `pending` entry at each tick.

---

## Environment

| Env | Default | Description |
| --- | --- | --- |
| `SHIPIT_LLM` | `bedrock` | Provider: `bedrock`, `openai`, `anthropic`, `ollama`, `groq`, `gemini` |
| `SHIPIT_MODEL` | provider default | Override model id (e.g. `claude-sonnet-5-5`) |
| `AWS_REGION` / `AWS_PROFILE` | — | Standard Bedrock auth |
| `OPENAI_API_KEY` | — | OpenAI key |
| `ANTHROPIC_API_KEY` | — | Anthropic key |

Run `shipit autopilot --help`, `shipit daemon --help`, or `shipit
queue --help` at the command line for the authoritative flag list.

---

## Format modes at a glance

```
$ shipit autopilot "..." --format tui

┌── Autopilot ── run-1713710400
│ Goal: Migrate every SQL call in src/ to parameterized form
│   1. No raw string concat remains
│   2. All tests pass
│
│ [tool] grep_search   (query='db.raw\(')    ok
│ ✓ iter 1 — 1/2 criteria · 3 tools · 12s · 14k tok
│ ♥ heartbeat iter=1 criteria=1/2 t=62s
│ 🎯 all criteria satisfied
└── result: COMPLETED · 4 iters · 11 tools · 82s · 58k tok
```

```
$ shipit autopilot "..." --format jsonl
{"kind":"autopilot.run_started","run_id":"r-...","goal":{...}}
{"kind":"autopilot.iteration","iteration":1,"criteria_met":[true,false],"usage":{...}}
{"kind":"autopilot.artifact","artifact_kind":"code","name":"iter1-block1.py",...}
{"kind":"autopilot.result","status":"completed",...}
```

`jsonl` pairs naturally with `jq` and log shippers.
