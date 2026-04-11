# Supervisor & Workers

Hierarchical agent that plans, delegates to workers, reviews quality, and sends work back for revision.

## Quick start — with_builtins

```python
from shipit_agent.deep import Supervisor

supervisor = Supervisor.with_builtins(
    llm=llm,
    worker_configs=[
        {"name": "researcher", "prompt": "You research topics using web search.", "capabilities": ["research"]},
        {"name": "writer", "prompt": "You write clear reports.", "capabilities": ["writing"]},
    ],
)
result = supervisor.run("Research AI trends and write a summary")
```

## Manual worker setup

```python
from shipit_agent import Agent, WebSearchTool, CodeExecutionTool
from shipit_agent.deep import Supervisor, Worker

researcher = Worker(
    name="researcher",
    agent=Agent(llm=llm, prompt="You research.", tools=[WebSearchTool()]),
    capabilities=["web search"],
)

coder = Worker(
    name="coder",
    agent=Agent(llm=llm, prompt="You write code.", tools=[CodeExecutionTool()]),
    capabilities=["coding"],
)

writer = Worker(
    name="writer",
    agent=Agent(llm=llm, prompt="You write reports."),  # no tools
)

supervisor = Supervisor(llm=llm, workers=[researcher, coder, writer], max_delegations=5)
```

## Agent.with_builtins per worker

```python
analyst = Worker(
    name="analyst",
    agent=Agent.with_builtins(llm=llm, prompt="You are a data analyst."),
)
# This worker has ALL 30+ tools
```

## Streaming delegations

```python
for event in supervisor.stream("Analyze data and write report"):
    worker = event.payload.get("worker", "supervisor")
    print(f"[{worker}] {event.message}")
    output = event.payload.get("output", "")
    if output:
        print(output[:300])
```

## With Super RAG — one shared knowledge base

Pass `rag=` to `Supervisor.with_builtins` and **every** worker is wired
with the same `RAG` instance. Sources captured by any worker show up in
the shared `result.rag_sources` panel.

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/api.md")

supervisor = Supervisor.with_builtins(
    llm=llm,
    worker_configs=[
        {"name": "researcher", "prompt": "You research the codebase."},
        {"name": "writer", "prompt": "You write user-facing answers."},
    ],
    rag=rag,
)
result = supervisor.run("Draft a release blog post about deep agents.")
```

## Supervisor inside a DeepAgent

A `Supervisor` is itself a perfectly valid sub-agent — drop it into a
parent `DeepAgent` and the parent gets a "team in a box" delegate:

```python
from shipit_agent.deep import DeepAgent

team = Supervisor.with_builtins(
    llm=llm,
    worker_configs=[
        {"name": "researcher", "prompt": "You research."},
        {"name": "writer",     "prompt": "You write."},
    ],
)

deep = DeepAgent.with_builtins(
    llm=llm,
    agents={"team": team},
)
deep.run("Use the team sub-agent to research and draft the release notes.")
```

## SupervisorResult fields

| Field | Type | Description |
|---|---|---|
| `output` | `str` | Final combined output |
| `delegations` | `list[Delegation]` | Round-by-round history |
| `total_rounds` | `int` | Rounds used |

Each `Delegation` has: `round`, `worker`, `task`, `output`, `approved`.

!!! tip "Notebook"
    `notebooks/19_supervisor_with_tools.ipynb`
