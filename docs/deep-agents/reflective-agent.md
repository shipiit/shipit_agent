# ReflectiveAgent

Agent that produces output, reflects critically with a quality score, and revises until the threshold is met.

## Quick start

```python
from shipit_agent.deep import ReflectiveAgent

agent = ReflectiveAgent.with_builtins(
    llm=llm,
    reflection_prompt="Check accuracy, completeness, clarity. Score 0-1.",
    max_reflections=3,
    quality_threshold=0.8,
)
result = agent.run("Explain the CAP theorem")
print(result.final_quality)   # 0.92
print(len(result.revisions))  # 2
```

## With web search

```python
agent = ReflectiveAgent.with_builtins(
    llm=llm,
    reflection_prompt="Verify facts by searching the web. Be strict.",
    quality_threshold=0.85,
)
result = agent.run("Write a guide on deploying FastAPI to AWS Lambda")
```

## Streaming reflections

```python
for event in agent.stream("Write a technical guide"):
    if event.type == "reasoning_completed":
        quality = event.payload.get("quality", 0)
        bar = "█" * int(quality * 10) + "░" * (10 - int(quality * 10))
        print(f"Quality: [{bar}] {quality:.2f}")
        print(f"Feedback: {event.payload.get('feedback', '')[:100]}")
    if event.type == "tool_completed":
        print(event.payload.get("output", "")[:200])
```

## With Super RAG

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/api.md")

agent = ReflectiveAgent.with_builtins(
    llm=llm,
    rag=rag,                           # auto-cited critique cycles
    reflection_prompt="Check accuracy against indexed docs.",
    quality_threshold=0.85,
)
result = agent.run("Explain how to stream events.")
```

## As a sub-agent of DeepAgent (the critic role)

`ReflectiveAgent` is a natural fit for the critic role inside a deep
agent that has multiple specialised workers:

```python
from shipit_agent import Agent
from shipit_agent.deep import DeepAgent, ReflectiveAgent

writer = Agent.with_builtins(llm=llm, name="writer")
critic = ReflectiveAgent.with_builtins(llm=llm, name="critic", quality_threshold=0.85)

deep = DeepAgent.with_builtins(llm=llm, agents=[writer, critic])
result = deep.run("Draft and review the API guide.")
```

When the parent calls `delegate_to_agent(agent_name="critic", task=...)`,
the reflection cycle runs inside the sub-agent and the events stream
back through `tool_completed.metadata['events']`.

## ReflectionResult fields

| Field | Type | Description |
|---|---|---|
| `output` | `str` | Final revised output |
| `final_quality` | `float` | Last quality score (0-1) |
| `reflections` | `list[Reflection]` | Each reflection's feedback + score |
| `revisions` | `list[str]` | Each version of the output |
| `iterations` | `int` | Number of reflection cycles |

!!! tip "Notebook"
    `notebooks/21_reflective_agent_web_research.ipynb`
