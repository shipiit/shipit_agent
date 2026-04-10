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
