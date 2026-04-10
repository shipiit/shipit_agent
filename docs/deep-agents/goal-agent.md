# GoalAgent

Autonomous agent that decomposes goals into sub-tasks, executes them using tools, and tracks progress against explicit success criteria.

## Quick start

```python
from shipit_agent.deep import GoalAgent, Goal

agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Research Python web frameworks",
        success_criteria=["Covers Django, Flask, FastAPI", "Includes benchmarks"],
        max_steps=5,
    ),
)
result = agent.run()
print(result.goal_status)   # "completed" | "partial" | "failed"
print(result.criteria_met)  # [True, True]
```

## With specific tools

```python
from shipit_agent import WebSearchTool, CodeExecutionTool

agent = GoalAgent(
    llm=llm,
    tools=[WebSearchTool(), CodeExecutionTool()],
    goal=Goal(objective="Calculate compound interest", success_criteria=["Shows formula", "Verifies with code"]),
)
```

## Streaming with output

```python
for event in agent.stream():
    print(f"{event.message}")
    output = event.payload.get("output", "")
    if output:
        print(output[:300])
    criteria = event.payload.get("criteria_met")
    if criteria:
        print(f"Criteria: {criteria}")
```

## With memory

```python
from shipit_agent import AgentMemory

memory = AgentMemory.default(llm=llm, embedding_fn=embed)

# Run 1
agent1 = GoalAgent(llm=llm, memory=memory, goal=goal1)
result1 = agent1.run()
memory.add_fact(f"Research: {result1.output[:500]}")

# Run 2 — remembers Run 1
agent2 = GoalAgent(llm=llm, memory=memory, goal=goal2)
result2 = agent2.run()
```

## GoalResult fields

| Field | Type | Description |
|---|---|---|
| `output` | `str` | Final output text |
| `goal_status` | `str` | `"completed"`, `"partial"`, `"failed"` |
| `criteria_met` | `list[bool]` | Per-criterion pass/fail |
| `steps_taken` | `int` | Steps executed |
| `step_outputs` | `list[dict]` | Per-step task and output |

!!! tip "Notebook"
    `notebooks/20_goal_agent_with_tools.ipynb`
