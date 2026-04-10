# Mid-Run Re-Planning

By default, the planner runs once before the agent loop starts. For complex, multi-step tasks, the agent can drift off-plan as it discovers new information. Mid-run re-planning adds checkpoints that let the planner re-evaluate progress and correct course.

## Enabling re-planning

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent.with_builtins(
    llm=OpenAIChatLLM(model="gpt-4o"),
    max_iterations=10,
    replan_interval=3,   # re-plan every 3 iterations
)

result = agent.run("Research and compare 5 cloud providers, then write a report")
```

## How it works

```
Iteration 1:  LLM calls web_search
Iteration 2:  LLM calls open_url
Iteration 3:  LLM calls web_search
              ↓
              Planner re-runs with current state
              "You've searched 2 providers. Continue with the remaining 3."
              ↓
Iteration 4:  LLM calls web_search (adjusted approach)
Iteration 5:  LLM calls open_url
Iteration 6:  LLM calls code_execution
              ↓
              Planner re-runs again
              "Data collected. Write the comparison report now."
              ↓
Iteration 7:  LLM writes the report
```

The planner output is injected as a `user`-role context message (not as a tool result), keeping Bedrock tool pairing balanced.

## When to use it

| Scenario | `replan_interval` | `max_iterations` |
|---|---|---|
| Simple query, 1-2 tools | `0` (disabled) | `4` |
| Research task, 3-5 tools | `3` | `8` |
| Complex workflow, many steps | `2` | `12` |
| Very long autonomous tasks | `3` | `20` |

!!! tip
    Re-planning only fires if `auto_plan=True` in the `RouterPolicy` and the prompt matches planning keywords. It won't re-plan if the planner tool isn't registered.

## Via the profile builder

```python
from shipit_agent import AgentProfileBuilder

profile = (
    AgentProfileBuilder("deep-researcher")
    .max_iterations(12)
    .replan_interval(3)
    .build_profile()
)
```

## Observing re-planning events

Re-planning emits the same `planning_started` / `planning_completed` events as the initial plan:

```python
for event in agent.stream("Complex research task"):
    if event.type == "planning_started":
        print("Planning/re-planning...")
    elif event.type == "planning_completed":
        print(f"Plan: {event.payload['output'][:100]}")
```

Count the `planning_started` events to see how many times the planner ran:

```python
result = agent.run("Build a comprehensive analysis")
plan_count = sum(1 for e in result.events if e.type == "planning_started")
print(f"Planner ran {plan_count} time(s)")
```
