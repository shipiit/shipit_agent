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
