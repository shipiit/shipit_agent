# `shipit_agent.safety`

What may run, and repairing what the model sends.

| Module | What it does |
|---|---|
| `action_detection.py` | Provider-neutral detection of unparsed model action attempts |
| `askuser_channel.py` | Non-blocking ask_user side-channel |
| `guardrails.py` | Guardrails — content-level protection around every agent run |
| `hitl.py` | Human-in-the-loop approval — one reusable console prompt for any agent |
| `hooks.py` | Lifecycle hooks that can observe a run, and block or rewrite prompts and tool calls |
| `lockdown.py` | Lockdown — once the agent reads something sensitive, it may only read |
| `permissions.py` | Permission engine — a fast, rule-based control plane for tool calls |
| `tool_healing.py` | Self-healing tool calls — promote text-emitted calls to structured ones |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
