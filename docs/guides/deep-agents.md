# Deep Agents

SHIPIT Agent's deep agent system provides autonomous, self-directing agent capabilities that go beyond any existing framework. All deep agents support **MCP servers**, **built-in tools** (web search, code execution, file operations), **real-time streaming**, and the full agent configuration.

Use `.with_builtins()` on any deep agent for instant access to all capabilities.

!!! tip "Runnable examples"
    - `python examples/11_deep_agents.py` — all deep agents in one script
    - `python examples/08_structured_output.py` — Pydantic & JSON schema output
    - `python examples/09_pipeline.py` — sequential, parallel, conditional
    - `python examples/10_agent_team.py` — multi-agent team with streaming
    - `python examples/12_advanced_memory.py` — all memory types
    - Notebooks: `notebooks/14_deep_agents.ipynb`, `notebooks/16_deep_agents_streaming.ipynb`, `notebooks/17_deep_agents_real_world.ipynb`, `notebooks/18_deep_agents_with_memory.ipynb`

---

## Goal Agent — Autonomous Goal Decomposition

`GoalAgent` decomposes goals into sub-tasks, executes them using tools, and tracks progress against explicit success criteria. It self-evaluates after each step.

### Basic usage

```python
from shipit_agent.deep import GoalAgent, Goal

agent = GoalAgent(
    llm=llm,
    goal=Goal(
        objective="Compare Python async libraries",
        success_criteria=[
            "Covers asyncio, trio, and curio",
            "Includes pros and cons for each",
            "Provides a recommendation",
        ],
        max_steps=5,
    ),
)

result = agent.run()
print(result.goal_status)    # "completed" | "partial" | "failed"
print(result.criteria_met)   # [True, True, True]
print(result.steps_taken)    # 3
```

### With built-in tools + MCP (full power)

```python
agent = GoalAgent.with_builtins(
    llm=llm,
    mcps=[github_mcp, figma_mcp],     # attach any MCP servers
    goal=Goal(
        objective="Research the top 3 Python web frameworks and create a comparison",
        success_criteria=[
            "Covers Django, Flask, and FastAPI",
            "Includes performance benchmarks",
            "Provides a recommendation based on use case",
        ],
        max_steps=8,
    ),
)

result = agent.run()
# Agent searched the web, analyzed results, wrote comparison
```

### Streaming — watch every step live

```python
for event in agent.stream():
    if event.type == "run_started":
        print(f"GOAL: {event.payload['objective']}")
    elif event.type == "planning_completed":
        print(f"PLAN: {event.payload['subtasks']}")
    elif event.type == "step_started":
        print(f"  >> {event.message}")
    elif event.type == "tool_called":
        print(f"     TOOL: {event.message}")
    elif event.type == "tool_completed":
        criteria = event.payload.get("criteria_met")
        if criteria:
            print(f"     EVAL: {criteria}")
    elif event.type == "run_completed":
        print(f"  STATUS: {event.payload.get('status')}")
```

### Inspecting results

```python
result = agent.run()

# Step-by-step progress
for s in result.step_outputs:
    print(f"Step {s['step']}: {s['task'][:60]}...")
    print(f"  Output: {s['output'][:100]}...")

# Serialize
print(result.to_dict())
```

---

## Reflective Agent — Self-Improvement Loop

`ReflectiveAgent` produces output, critically reflects on it, and revises until quality meets the threshold. The agent becomes its own reviewer.

### Basic usage

```python
from shipit_agent.deep import ReflectiveAgent

agent = ReflectiveAgent(
    llm=llm,
    reflection_prompt="Check for: accuracy, completeness, clarity. Be critical.",
    max_reflections=3,
    quality_threshold=0.8,
)

result = agent.run("Explain the CAP theorem")
print(result.final_quality)     # 0.92
print(result.iterations)        # 2
print(len(result.revisions))    # 3 (initial + 2 revisions)
```

### With built-in tools — research and verify

```python
agent = ReflectiveAgent.with_builtins(
    llm=llm,
    mcps=[my_mcp_server],
    reflection_prompt="Verify facts by searching the web. Check accuracy and completeness.",
    max_reflections=3,
    quality_threshold=0.85,
)

result = agent.run("Write a guide on deploying FastAPI to AWS Lambda")
# Agent writes -> reflects -> searches web to verify -> revises
```

### Streaming reflections

```python
for event in agent.stream("Write a technical guide"):
    if event.type == "reasoning_started":
        print("REFLECTING...")
    elif event.type == "reasoning_completed":
        print(f"  Quality: {event.payload['quality']:.2f}")
        print(f"  Feedback: {event.payload['feedback'][:100]}")
    elif event.type == "run_completed":
        print(f"  FINAL QUALITY: {event.payload.get('quality')}")
```

### Inspecting reflections

```python
result = agent.run("Explain transformers")

for i, r in enumerate(result.reflections, 1):
    print(f"Reflection {i}: quality={r.quality_score:.2f}")
    print(f"  Feedback: {r.feedback[:100]}")
    print(f"  Needs revision: {r.revision_needed}")

# Each revision
for i, rev in enumerate(result.revisions):
    print(f"Version {i + 1}: {rev[:100]}...")
```

---

## Adaptive Agent — Runtime Tool Creation

`AdaptiveAgent` can create new tools at runtime when it needs capabilities it doesn't have. Code is auto-dedented so it works cleanly in notebooks.

### Creating tools dynamically

```python
from shipit_agent.deep import AdaptiveAgent
from shipit_agent.tools.base import ToolContext

agent = AdaptiveAgent(llm=llm, can_create_tools=True)

# Create a Fibonacci tool
fib = agent.create_tool(
    name="fibonacci",
    description="Calculate the Nth Fibonacci number",
    code="""
    def fibonacci(n: int) -> str:
        if n <= 1:
            return str(n)
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return str(b)
    """,
)

# Test it directly
print(fib.run(ToolContext(prompt="test"), n=10).text)  # "55"

# Create a temperature converter
agent.create_tool(
    name="celsius_to_fahrenheit",
    description="Convert Celsius to Fahrenheit",
    code="""
    def celsius_to_fahrenheit(celsius: float) -> str:
        return f"{celsius}C = {celsius * 9/5 + 32:.1f}F"
    """,
)

# All created tools are available for agent runs
print(agent.created_tools)        # [CreatedTool(name="fibonacci"), ...]
print(len(agent.tools))           # 2
result = agent.run("What is fibonacci of 20?")
```

### With built-in tools

```python
# Full power — web search + code exec + dynamic tool creation
agent = AdaptiveAgent.with_builtins(llm=llm, can_create_tools=True)
agent.create_tool("csv_parser", "Parse CSV", "def csv_parser(path: str) -> str: ...")
result = agent.run("Search for CSV parsing best practices, then analyze data.csv")
```

### Streaming

```python
for event in agent.stream("Analyze the dataset"):
    print(f"[{event.type}] {event.message}")
```

---

## Supervisor — Hierarchical Agent Management

`Supervisor` plans work, delegates to specialized workers, reviews quality, and can send work back for revision. More powerful than `AgentTeam` — active quality monitoring.

### Quick setup with built-in tools

```python
from shipit_agent.deep import Supervisor, Worker

supervisor = Supervisor.with_builtins(
    llm=llm,
    worker_configs=[
        {
            "name": "trend-researcher",
            "prompt": "You are a trend researcher. Search the web for trends. Return bullet points.",
            "capabilities": ["web search", "research"],
        },
        {
            "name": "content-writer",
            "prompt": "You write viral social media posts with emojis and hashtags.",
            "capabilities": ["writing", "social media"],
        },
        {
            "name": "reviewer",
            "prompt": "You review content for engagement and brand safety. Rate 1-10.",
            "capabilities": ["review", "quality"],
        },
    ],
    mcps=[my_mcp_server],       # all workers get MCP access
    max_delegations=6,
)

result = supervisor.run("Create 3 viral posts about AI agents for developers")
```

### Manual worker setup (more control)

```python
from shipit_agent import Agent

analyst = Worker(
    name="data-analyst",
    agent=Agent.with_builtins(llm=llm, prompt="You are a data analyst."),
    capabilities=["data", "statistics", "pandas"],
)

writer = Worker(
    name="report-writer",
    agent=Agent(llm=llm, prompt="You write executive summaries."),
    capabilities=["writing", "reports"],
)

supervisor = Supervisor(llm=llm, workers=[analyst, writer], max_delegations=5)
result = supervisor.run("Analyze AI adoption trends and write a summary")
```

### Inspecting delegations

```python
result = supervisor.run("Build a report")

for d in result.delegations:
    print(f"Round {d.round}: [{d.worker}]")
    print(f"  Task: {d.task[:80]}...")
    print(f"  Output: {d.output[:120]}...")
    print(f"  Approved: {d.approved}")

print(f"Total rounds: {result.total_rounds}")
print(result.to_dict())  # serialize
```

### Streaming — watch delegation in real time

```python
for event in supervisor.stream("Create a marketing report"):
    worker = event.payload.get("worker", "supervisor")
    if event.type == "planning_started":
        print(f"[supervisor] Planning next step...")
    elif event.type == "tool_called":
        print(f"[supervisor] Delegating to {worker}: {event.message}")
    elif event.type == "tool_completed":
        print(f"[{worker}] Done: {event.payload.get('output', '')[:80]}")
    elif event.type == "run_completed":
        print(f"[supervisor] Finished in {event.payload.get('rounds')} rounds")
```

---

## Persistent Agent — Checkpoint & Resume

`PersistentAgent` saves progress periodically so long-running tasks survive crashes, timeouts, or user interruptions.

### Basic usage

```python
from shipit_agent.deep import PersistentAgent

agent = PersistentAgent(
    llm=llm,
    tools=[web_search, code_exec],
    checkpoint_dir="./checkpoints",
    checkpoint_interval=5,     # save every 5 steps
    max_steps=50,
)

# Start a long task
result = agent.run("Write a 50-page report on AI regulations", agent_id="ai-report")

# If interrupted, resume exactly where you left off
result = agent.resume(agent_id="ai-report")
```

### Check progress without resuming

```python
status = agent.status("ai-report")
# {"state": "paused", "agent_id": "ai-report", "steps_done": 20, "outputs_count": 20}

# Or "not_found" if no checkpoint exists
status = agent.status("nonexistent")
# {"state": "not_found"}
```

---

## Agent Communication — Typed Channels

`Channel` enables structured, typed message passing between agents. Every message has a sender, receiver, type, structured data, and optional acknowledgment.

### Full pipeline example

```python
from shipit_agent.deep import Channel, AgentMessage
from shipit_agent import Agent

channel = Channel(name="content-pipeline")

# --- Step 1: Researcher gathers info ---
researcher = Agent.with_builtins(llm=llm, prompt="You are a researcher.")
research = researcher.run("Find 5 key facts about WebAssembly adoption")

channel.send(AgentMessage(
    from_agent="researcher",
    to_agent="writer",
    type="research_complete",
    data={
        "findings": research.output,
        "word_count": len(research.output.split()),
        "confidence": 0.92,
    },
    requires_ack=True,
))

# --- Step 2: Writer receives, acknowledges, writes ---
msg = channel.receive(agent="writer")
print(f"From: {msg.from_agent}, Type: {msg.type}")
print(f"Confidence: {msg.data['confidence']}")
channel.ack(msg)                    # acknowledge receipt

writer = Agent(llm=llm, prompt="You are a technical writer.")
draft = writer.run(f"Write a summary using: {msg.data['findings']}")

channel.send(AgentMessage(
    from_agent="writer",
    to_agent="reviewer",
    type="draft_ready",
    data={"draft": draft.output},
))

# --- Step 3: Reviewer receives and reviews ---
review_msg = channel.receive(agent="reviewer")
reviewer = Agent(llm=llm, prompt="You are an editor. Rate 1-10.")
review = reviewer.run(f"Review: {review_msg.data['draft']}")

channel.send(AgentMessage(
    from_agent="reviewer",
    to_agent="writer",
    type="review_complete",
    data={"review": review.output, "status": "approved"},
))

# --- Inspect channel ---
print(f"Messages sent: {len(channel.history())}")
print(f"Pending for writer: {channel.pending(agent='writer')}")

for msg in channel.history():
    print(f"  {msg.from_agent} -> {msg.to_agent} [{msg.type}] ack={msg.acknowledged}")
```

### Multi-agent queues

```python
channel = Channel()

# Send to different agents
channel.send(AgentMessage(from_agent="manager", to_agent="dev1", type="task", data={"work": "build API"}))
channel.send(AgentMessage(from_agent="manager", to_agent="dev2", type="task", data={"work": "write tests"}))
channel.send(AgentMessage(from_agent="manager", to_agent="dev1", type="task", data={"work": "fix bug"}))

# Each agent gets their own queue
print(channel.pending(agent="dev1"))  # 2
print(channel.pending(agent="dev2"))  # 1

# Messages are FIFO per agent
msg1 = channel.receive(agent="dev1")  # "build API"
msg2 = channel.receive(agent="dev1")  # "fix bug"
```

### Message serialization

```python
msg = AgentMessage(from_agent="a", to_agent="b", type="data", data={"key": "value"})
print(msg.to_dict())
# {"from": "a", "to": "b", "type": "data", "data": {"key": "value"}, ...}
```

---

## Agent Benchmarking — Systematic Testing

`AgentBenchmark` tests your agents systematically with expected outputs, tool usage, and content checks.

### Define test cases

```python
from shipit_agent.deep import AgentBenchmark, TestCase

benchmark = AgentBenchmark(
    name="Programming Knowledge Eval",
    cases=[
        TestCase(
            input="What is Python's GIL?",
            expected_contains=["global interpreter lock", "thread"],
        ),
        TestCase(
            input="Explain REST APIs",
            expected_contains=["http", "resource"],
            expected_not_contains=["graphql"],
        ),
        TestCase(
            input="What are Python decorators?",
            expected_contains=["function", "wrap"],
        ),
        TestCase(
            input="What is Docker?",
            expected_contains=["container"],
            expected_tools=["web_search"],  # check tool usage
        ),
    ],
)
```

### Run and get report

```python
agent = Agent.with_builtins(llm=llm)
report = benchmark.run(agent)

print(report.summary())
# Agent Benchmark: Programming Knowledge Eval
# Cases: 4 passed, 0 failed (4 total)
# Pass rate: 100%
# Avg iterations: 1.5
# Tools used: web_search(2)
#   [PASS] What is Python's GIL?
#   [PASS] Explain REST APIs
#   [PASS] What are Python decorators?
#   [PASS] What is Docker?
```

### Inspect failures

```python
for r in report.results:
    if not r.passed:
        print(f"FAILED: {r.test_case.input}")
        for f in r.failures:
            print(f"  - {f}")
        print(f"  Output: {r.output[:200]}")
```

### Export for dashboards

```python
import json
print(json.dumps(report.to_dict(), indent=2))
# {"name": "...", "passed": 4, "failed": 0, "pass_rate": 1.0, "results": [...]}
```

---

## Combining Deep Agents

### Pipeline + Supervisor

```python
from shipit_agent import Pipeline, step

supervisor = Supervisor.with_builtins(llm=llm, worker_configs=[...])

pipe = Pipeline.sequential(
    step("research", agent=Agent.with_builtins(llm=llm), prompt="Research {topic}"),
    step("produce", fn=lambda text: supervisor.run(f"Create content from: {text}").output),
)
result = pipe.run(topic="AI agents")
```

### GoalAgent + Channel

```python
channel = Channel()
agent = GoalAgent.with_builtins(llm=llm, goal=goal)

for event in agent.stream():
    # Forward events through a channel
    channel.send(AgentMessage(
        from_agent="goal_agent", to_agent="monitor",
        type=event.type, data=event.payload,
    ))
```

### ReflectiveAgent + Benchmark

```python
agent = ReflectiveAgent.with_builtins(llm=llm, quality_threshold=0.9)

# Benchmark the reflective agent
benchmark = AgentBenchmark(name="quality-check", cases=[
    TestCase(input="Explain quantum computing", expected_contains=["qubit", "superposition"]),
])
report = benchmark.run(agent)
```

---

## Deep Agents with Memory

All deep agents accept a `memory` parameter. Pass an `AgentMemory` instance to give agents persistent conversation history, semantic knowledge, and entity tracking across multiple runs.

### GoalAgent with memory — remembers previous goals

```python
from shipit_agent import AgentMemory, ConversationMemory, SemanticMemory, EntityMemory, Entity, InMemoryVectorStore

# Create shared memory
memory = AgentMemory(
    conversation=ConversationMemory(strategy="buffer"),
    knowledge=SemanticMemory(vector_store=InMemoryVectorStore(), embedding_fn=embed),
    entities=EntityMemory(),
)

# Run 1: Research frameworks
agent1 = GoalAgent(
    llm=llm,
    memory=memory,
    goal=Goal(objective="List top 3 Python web frameworks", success_criteria=["Names Django, Flask, FastAPI"]),
)
result1 = agent1.run()

# Store findings in memory
memory.add_fact(f"Previous research: {result1.output[:500]}")
memory.add_entity(Entity(name="Django", entity_type="framework", context="Python web framework"))
memory.add_entity(Entity(name="FastAPI", entity_type="framework", context="Modern async framework"))

# Run 2: Agent remembers Run 1!
agent2 = GoalAgent(
    llm=llm,
    memory=memory,   # same memory — agent sees previous conversation
    goal=Goal(objective="Compare the performance of the frameworks you found earlier", success_criteria=["References Django, Flask, FastAPI"]),
)
result2 = agent2.run()
# Agent has context from Run 1 and can reference previous findings
```

### ReflectiveAgent with memory — learns from reflections

```python
memory = AgentMemory.default(llm=llm, embedding_fn=embed)

reflective = ReflectiveAgent(
    llm=llm,
    memory=memory,
    reflection_prompt="Check accuracy and completeness.",
    quality_threshold=0.8,
)

# Run 1: Explain REST
result1 = reflective.run("Explain what a REST API is")
memory.add_fact(f"REST explanation quality: {result1.final_quality:.2f}")

# Run 2: Compare with GraphQL — agent remembers the REST explanation
result2 = reflective.run("Now explain GraphQL and compare it to REST")
# Agent has full REST context from memory
```

### Supervisor with shared memory — workers share knowledge

```python
# Pre-load business data
team_memory = AgentMemory.default(embedding_fn=embed)
team_memory.add_fact("Q4 2025 revenue: $2.4M, up 15% YoY")
team_memory.add_fact("Customer satisfaction: 92%")
team_memory.add_entity(Entity(name="Product Atlas", entity_type="product", context="Main SaaS platform"))

# Workers share memory via history
analyst = Worker(
    name="analyst",
    agent=Agent(llm=llm, prompt="You are a data analyst.", history=team_memory.get_conversation_messages()),
)
writer = Worker(
    name="writer",
    agent=Agent(llm=llm, prompt="You write reports.", history=team_memory.get_conversation_messages()),
)

supervisor = Supervisor(llm=llm, workers=[analyst, writer])
result = supervisor.run("Write a Q4 executive summary using the data we have")
```

### How memory flows through deep agents

```
AgentMemory
├── ConversationMemory
│   └── Messages from all previous runs are injected as agent history
├── SemanticMemory
│   └── Facts stored/searched by embedding similarity
└── EntityMemory
    └── People, projects, concepts tracked across sessions

GoalAgent(memory=memory)
  └── _build_agent() injects memory.get_conversation_messages() as history
  └── _save_to_memory() stores each step's output
  └── Result: agent sees full conversation context from prior runs

ReflectiveAgent(memory=memory)
  └── Same pattern — history injected, outputs saved
  └── Store reflection feedback as facts for future runs

Supervisor(workers=[...])
  └── Each worker gets history= from shared memory
  └── Workers can access pre-loaded facts and entities
```

!!! tip "Notebook"
    See `notebooks/18_deep_agents_with_memory.ipynb` for full runnable examples with Bedrock.
