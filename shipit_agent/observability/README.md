# `shipit_agent.observability`

What a run shows while it runs, and accounting after it.

| Module | What it does |
|---|---|
| `activity.py` | Human-readable activity traces — Claude-Code-style tool cards |
| `live.py` | A typed live stream of what the agent is doing, tool output included |
| `live_renderer.py` | Live TUI renderer for ``Autopilot.stream()`` — Claude-Desktop-style |
| `streaming.py` | Two streams, not one — what a web client needs to render a live run |
| `tracing.py` | Trace records for a run and the stores that keep them (in memory or on disk) |
| `usage.py` | Accounting for every completion, including the ones nobody watches |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
