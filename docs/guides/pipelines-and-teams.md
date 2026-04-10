# Pipelines & Agent Teams

Two composition systems for multi-agent workflows: **Pipeline** for deterministic flows, **AgentTeam** for dynamic LLM-routed collaboration.

---

## Pipeline — Deterministic Composition

Chain agents and functions together like UNIX pipes. Steps reference previous results via `{step_name.output}` templates.

### Sequential pipeline

```python
from shipit_agent import Agent, Pipeline, step
from shipit_agent.llms import OpenAIChatLLM

llm = OpenAIChatLLM(model="gpt-4o-mini")

researcher = Agent(llm=llm, prompt="You are a research expert. Return key facts.")
writer = Agent(llm=llm, prompt="You are a technical writer. Write clear content.")

pipe = Pipeline.sequential(
    step("research", agent=researcher, prompt="Find key facts about {topic}"),
    step("write", agent=writer, prompt="Write an article using:\n{research.output}"),
)

result = pipe.run(topic="quantum computing")
print(result.steps["research"].output)  # research findings
print(result.output)                     # final article
print(result.to_dict())                  # serialize everything
```

### Parallel fan-out — run steps concurrently

```python
from shipit_agent import Pipeline, step, parallel

pros_agent = Agent(llm=llm, prompt="List only the pros. Be concise.")
cons_agent = Agent(llm=llm, prompt="List only the cons. Be concise.")
synthesizer = Agent(llm=llm, prompt="You are a balanced analyst.")

pipe = Pipeline(
    # These 2 steps run concurrently via ThreadPoolExecutor
    parallel(
        step("pros", agent=pros_agent, prompt="Pros of {topic}"),
        step("cons", agent=cons_agent, prompt="Cons of {topic}"),
    ),
    # This step runs after both parallel steps complete
    step("synthesis", agent=synthesizer, prompt="""Combine these viewpoints:

Pros: {pros.output}

Cons: {cons.output}"""),
)

result = pipe.run(topic="microservices architecture")
print(result.steps["pros"].output)     # pros analysis
print(result.steps["cons"].output)     # cons analysis
print(result.output)                    # balanced synthesis
```

### Function steps — mix agents with plain Python

No LLM call needed for deterministic transforms:

```python
def word_count(text: str) -> str:
    words = len(text.split())
    return f"[{words} words]\n\n{text}"

def to_uppercase(text: str) -> str:
    return text.upper()

pipe = Pipeline.sequential(
    step("generate", agent=Agent(llm=llm), prompt="Write a haiku about {topic}"),
    step("stats", fn=word_count),         # pure Python — no LLM
    step("shout", fn=to_uppercase),       # another pure function
)

result = pipe.run(topic="coding")
print(result.steps["generate"].output)  # the haiku
print(result.steps["stats"].output)     # "[17 words]\n\n..."
print(result.output)                     # UPPERCASED
```

### Conditional routing — branch based on results

```python
classifier = Agent(llm=llm, prompt="Reply with just 'question' or 'statement'.")
question_agent = Agent(llm=llm, prompt="You answer questions concisely.")
statement_agent = Agent(llm=llm, prompt="You acknowledge statements and add context.")

pipe = Pipeline.sequential(
    step("classify", agent=classifier, prompt="{input}"),
    step("handle",
         router=lambda ctx: "question" if "question" in ctx["classify"].output.lower() else "statement",
         branches={
             "question": step("answer", agent=question_agent, prompt="{input}"),
             "statement": step("respond", agent=statement_agent, prompt="{input}"),
         }),
)

result = pipe.run(input="What is the speed of light?")
# Classified as "question" -> routed to question_agent
```

### Structured output in pipeline steps

```python
from pydantic import BaseModel

class Analysis(BaseModel):
    sentiment: str
    confidence: float

pipe = Pipeline.sequential(
    step("analyze", agent=Agent(llm=llm), prompt="Analyze: {text}", output_schema=Analysis),
)
result = pipe.run(text="SHIPIT is amazing!")
# result.steps["analyze"].metadata["parsed"] has the Analysis instance
```

### Real-world example: Content production pipeline

```python
import time

researcher = Agent.with_builtins(llm=llm, prompt="You are a research analyst.")
analyzer = Agent(llm=llm, prompt="You identify trends from research.")
writer = Agent(llm=llm, prompt="You write polished content.")

pipe = Pipeline(
    parallel(
        step("research", agent=researcher, prompt="Research {topic} in 2025"),
        step("trends", agent=analyzer, prompt="Top 3 trends in {topic}"),
    ),
    step("article", agent=writer, prompt="""Write a 3-paragraph article using:

Research: {research.output}
Trends: {trends.output}"""),
    step("final", fn=lambda text: f"[{len(text.split())} words]\n\n{text}"),
)

start = time.time()
result = pipe.run(topic="AI developer tools")
print(f"Completed in {time.time() - start:.1f}s")
print(result.output)
```

---

## Agent Team — Dynamic LLM-Routed Collaboration

Define agents with roles. A coordinator LLM decides who works, in what order, when to loop back. No graph wiring needed.

### Basic team

```python
from shipit_agent import AgentTeam, TeamAgent, Agent

researcher = TeamAgent(
    name="researcher",
    role="Expert at finding information from the web",
    agent=Agent.with_builtins(llm=llm),
    capabilities=["research", "web search"],
)

writer = TeamAgent(
    name="writer",
    role="Expert at writing clear, engaging content",
    agent=Agent(llm=llm, prompt="You are a skilled writer."),
    capabilities=["writing", "editing"],
)

reviewer = TeamAgent(
    name="reviewer",
    role="Checks content for accuracy. Can send work back for revision.",
    agent=Agent(llm=llm, prompt="You are a critical reviewer."),
    capabilities=["review", "quality"],
)

team = AgentTeam(
    name="content-team",
    coordinator=llm,
    agents=[researcher, writer, reviewer],
    max_rounds=10,
)

result = team.run("Write a comprehensive guide about async Python")
```

### Quick setup with `.with_builtins()`

```python
researcher = TeamAgent.with_builtins(
    name="researcher",
    role="Expert at web research and finding key facts",
    llm=llm,
    mcps=[github_mcp],           # attach MCP servers
    capabilities=["research"],
)
```

### Inspecting delegation history

```python
result = team.run("Write a guide")

for r in result.rounds:
    print(f"Round {r.number}: [{r.agent}]")
    print(f"  Task: {r.prompt[:80]}...")
    print(f"  Output: {r.output[:100]}...")

print(result.to_dict())  # serialize
```

### How it works

1. Coordinator sees the task and all agent descriptions
2. Decides which agent should go first (returns JSON)
3. Selected agent runs, produces output
4. Coordinator reviews output, decides next step
5. Can route back to a previous agent for revision
6. Continues until coordinator says "done" or `max_rounds` hit

### When to use Pipeline vs Team

| Use case | Pipeline | Team |
|---|---|---|
| Steps are known in advance | Yes | |
| Order depends on results | | Yes |
| Need revision loops | | Yes |
| Deterministic, reproducible | Yes | |
| Dynamic, adaptive | | Yes |
| Mix agents with functions | Yes | |
| Streaming events | `pipe.stream()` | `team.stream()` |

---

## Streaming — Real-Time Events from Pipelines and Teams

Both Pipeline and AgentTeam support `.stream()` for watching execution in real time.

### Pipeline streaming

```python
pipe = Pipeline.sequential(
    step("research", agent=researcher, prompt="Research {topic}"),
    step("write", agent=writer, prompt="Write about: {research.output}"),
)

for event in pipe.stream(topic="AI agents"):
    if event.type == "step_started":
        print(f">> Starting: {event.payload['step']}")
    elif event.type == "tool_completed":
        print(f"   Done: {event.payload['step']} ({event.payload['output'][:60]}...)")
    elif event.type == "run_completed":
        print(f"Pipeline finished ({event.payload['steps_completed']} steps)")
```

Inner agent events are forwarded with `pipeline_step` tagged in the payload:

```python
for event in pipe.stream(topic="AI"):
    step_name = event.payload.get("pipeline_step", "pipeline")
    print(f"[{step_name}] {event.type}: {event.message}")
```

### Team streaming

```python
team = AgentTeam(coordinator=llm, agents=[researcher, writer, reviewer])

for event in team.stream("Write a guide about Python"):
    if event.type == "tool_called":
        print(f"Delegating to: {event.payload.get('agent')}")
    elif event.type == "tool_completed":
        print(f"Done: {event.payload.get('agent')}")
    elif event.type == "run_completed":
        print(f"Team finished: {event.payload.get('output', '')[:100]}")
```
