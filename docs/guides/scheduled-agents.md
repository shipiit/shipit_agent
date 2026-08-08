---
title: Scheduled Agents
description: Run durable jobs with independent models, runtimes, tools, skills, MCP servers, sessions, and live events.
---

# Scheduled agents

Each scheduled job can select its own provider, model, project, role, runtime,
permission policy, guardrails, MCP servers, skills, and persistent session.
One provider failure is isolated and does not stop other due jobs.

```python
from shipit_agent import (
    AgentScheduler,
    ScheduledAgentConfig,
    ScheduledAgentFactory,
    connect_mcp,
)
from shipit_agent.cli.llm import build_llm

factory = ScheduledAgentFactory(
    llm_factory=build_llm,
    mcp_factory=connect_mcp,
)
scheduler = AgentScheduler(
    agent_resolver=factory,
    on_event=lambda job, event: print(job.name, event.type, event.message),
)
scheduler.add(
    "Audit the repository and report release blockers.",
    cron="0 8 * * 1-5",
    name="release-audit",
    session_id="release-history",
    agent_config=ScheduledAgentConfig(
        provider="openai",
        model="gpt-5.5",
        project_root="/path/to/repo",
        runtime="project",
        optimized=True,
        permission_mode="plan",
        guardrails="strict",
        mcps=["github"],
        connections=["slack"],
        skills=["release-audit"],
        stream_events=True,
    ),
)
scheduler.run_forever()
```

`stream_events=True` routes live `AgentEvent` objects through the scheduler's
`on_event` callback and still returns a `ScheduleResult` when the run completes.
Use `SQLiteJobStore` for durable run counts, next-run times, pause state, failure
status, and complete agent configuration.

## CLI

```bash
shipit jobs add "Audit the release" \
  --cron "0 8 * * 1-5" \
  --name release-audit \
  --provider openai \
  --model gpt-5.5 \
  --project-root /path/to/repo \
  --permission-mode plan \
  --guardrails strict \
  --mcp github \
  --connection slack \
  --skill release-audit \
  --session-id release-history \
  --stream-events

shipit jobs list
shipit jobs pause release-audit
shipit jobs resume release-audit
shipit jobs start
```

Connection names are capability requirements, not stored credentials. Keep
tokens and secrets in the configured credential store or environment; the
scheduler database never persists them.
