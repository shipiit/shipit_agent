# Deep Agents Overview

SHIPIT Agent's deep agent system provides autonomous, self-directing agent capabilities that go beyond LangChain. All deep agents support **MCP servers**, **built-in tools**, **real-time streaming**, and **memory**.

| Agent | What it does | Key feature |
|---|---|---|
| [GoalAgent](goal-agent.md) | Decomposes goals, tracks success criteria | Autonomous multi-step execution |
| [ReflectiveAgent](reflective-agent.md) | Self-evaluates and revises output | Quality threshold with scores |
| [Supervisor](supervisor.md) | Delegates to workers, reviews quality | Hierarchical multi-agent |
| [AdaptiveAgent](adaptive-agent.md) | Creates new tools at runtime | Dynamic tool creation |
| [PersistentAgent](persistent-agent.md) | Checkpoint and resume | Long-running tasks |
| [Channel](channels.md) | Typed agent-to-agent messaging | Structured communication |
| [AgentBenchmark](benchmarking.md) | Systematic agent testing | Pass/fail reports |

All deep agents support:

```python
# All tools (web search, code exec, etc.)
agent = GoalAgent.with_builtins(llm=llm, goal=goal)

# Real-time streaming with output content
for event in agent.stream():
    print(event.payload.get("output", ""))

# Memory across runs
agent = GoalAgent(llm=llm, memory=memory, goal=goal)
```

!!! tip "Runnable examples"
    - `python examples/11_deep_agents.py` — all deep agents
    - Notebooks: `14`, `16`, `17`, `18`, `19`, `20`, `21`
