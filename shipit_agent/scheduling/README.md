# `shipit_agent.scheduling`

Runs that start themselves.

| Module | What it does |
|---|---|
| `daemon.py` | Scheduler daemon — keep an Autopilot queue running indefinitely |
| `schedule.py` | Scheduled agent runs: job definitions, a SQLite job store and the runner that executes due jobs |
| `triggers.py` | Triggers — an agent that reacts, not only one you ask |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
