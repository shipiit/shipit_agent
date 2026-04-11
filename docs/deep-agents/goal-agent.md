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

## With Super RAG (auto-cited answers)

Pass a `RAG` and the goal agent will use `rag_search` / `rag_fetch_chunk`
on every sub-task and capture sources into `result.rag_sources`:

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/release_notes.md")

agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Write release notes summary",
        success_criteria=["Mentions deep agents", "Mentions RAG"],
    ),
    rag=rag,
)

result = agent.run()
for src in result.rag_sources:
    print(f"[{src.index}] {src.source}: {src.text[:80]}")
```

## Inside a DeepAgent (as a sub-agent)

Use `GoalAgent` as one of the named delegates of a parent `DeepAgent`:

```python
from shipit_agent.deep import DeepAgent

shipper = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(objective="Ship the auth fix", success_criteria=["Tests pass"]),
)

deep = DeepAgent.with_builtins(
    llm=llm,
    agents={"shipper": shipper},
)
deep.run("Use the shipper sub-agent to land the auth fix.")
```

## Streaming with the parent context

When a `GoalAgent` is run as a sub-agent of a `DeepAgent`, every event
flows back through the parent's `tool_completed.metadata['events']`.
Drive the parent's stream and you can see exactly what each sub-task
is doing in real time.

```python
for event in deep.stream("Use the shipper to land the fix."):
    if event.type == "tool_completed":
        for inner in event.payload.get("metadata", {}).get("events", []):
            print(f"  ↳ {inner['type']}: {inner['message'][:80]}")
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
