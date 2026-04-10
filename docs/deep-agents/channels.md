# Channels — Agent Communication

Typed, structured message passing between agents. Each agent has its own FIFO queue with acknowledgment support.

## Quick start

```python
from shipit_agent.deep import Channel, AgentMessage

channel = Channel(name="pipeline")

# Send
channel.send(AgentMessage(
    from_agent="researcher",
    to_agent="writer",
    type="research_complete",
    data={"findings": ["Fact 1", "Fact 2"], "confidence": 0.92},
    requires_ack=True,
))

# Receive
msg = channel.receive(agent="writer")
print(msg.data["findings"])
channel.ack(msg)

# Check state
print(channel.pending(agent="writer"))  # 0
print(len(channel.history()))           # 1
```

## Multi-agent queues

```python
channel.send(AgentMessage(from_agent="mgr", to_agent="dev1", type="task", data={"work": "API"}))
channel.send(AgentMessage(from_agent="mgr", to_agent="dev2", type="task", data={"work": "tests"}))
channel.send(AgentMessage(from_agent="mgr", to_agent="dev1", type="task", data={"work": "fix bug"}))

channel.pending(agent="dev1")  # 2
channel.pending(agent="dev2")  # 1
```

## AgentMessage fields

| Field | Type | Description |
|---|---|---|
| `from_agent` | `str` | Sender |
| `to_agent` | `str` | Receiver |
| `type` | `str` | Message type |
| `data` | `dict` | Structured payload |
| `requires_ack` | `bool` | Ack expected? |
| `acknowledged` | `bool` | Ack received? |
