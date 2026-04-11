# PersistentAgent

Agent that checkpoints progress periodically so long-running tasks survive crashes, timeouts, or interruptions. Resume exactly where you left off.

## Quick start

```python
from shipit_agent.deep import PersistentAgent

agent = PersistentAgent(
    llm=llm,
    tools=[...],
    checkpoint_dir="./checkpoints",
    checkpoint_interval=5,
    max_steps=50,
)

# Start a long task
result = agent.run("Write a comprehensive report", agent_id="report-1")

# If interrupted, resume from last checkpoint
result = agent.resume(agent_id="report-1")

# Check progress without resuming
status = agent.status("report-1")
# {"state": "paused", "steps_done": 20, "outputs_count": 20}
```

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `checkpoint_dir` | `.shipit_checkpoints` | Where to save checkpoints |
| `checkpoint_interval` | `5` | Save every N steps |
| `max_steps` | `50` | Maximum total steps |
| `rag` | `None` | Optional `RAG` instance forwarded to every inner Agent |

## Streaming with checkpoints

`PersistentAgent.stream(task, agent_id=...)` yields one event flow per
step plus a final `run_completed` event. Checkpoints are still written
every `checkpoint_interval` steps so the run can be resumed if
interrupted mid-stream.

```python
agent = PersistentAgent(
    llm=llm,
    rag=rag,
    checkpoint_interval=2,
    max_steps=10,
)

for event in agent.stream("Long research task", agent_id="task-42"):
    if event.type == "step_started":
        print(f"📍 step {event.payload['step']}")
    elif event.type == "tool_called":
        print(f"  ▶ {event.message}")
    elif event.type == "rag_sources":
        for s in event.payload.get("sources", []):
            print(f"  📎 [{s['index']}] {s['source']}")
    elif event.type == "run_completed":
        print(f"✓ {event.message} ({event.payload.get('steps')} steps)")
```

## With Super RAG

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/research_brief.md")

agent = PersistentAgent(llm=llm, rag=rag, checkpoint_interval=3, max_steps=20)
result = agent.run("Long research task", agent_id="task-1")
print("sources cited across the run:")
for src in result.rag_sources:
    print(f"  [{src.index}] {src.source}")
```

## Inside a DeepAgent

```python
from shipit_agent.deep import DeepAgent, PersistentAgent

batch = PersistentAgent(llm=llm, checkpoint_dir="./batch", max_steps=30)
deep = DeepAgent.with_builtins(llm=llm, agents={"long_runner": batch})
deep.run("Use long_runner to process the queue.")
```
