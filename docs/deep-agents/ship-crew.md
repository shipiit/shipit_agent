# ShipCrew

Multi-agent orchestration with DAG-based task execution. Compose specialised agents into workflows where tasks have dependencies, context flows automatically, and execution can be sequential, parallel, or LLM-coordinated.

## Quick start

```python
from shipit_agent import Agent
from shipit_agent.deep.ship_crew import ShipCrew, ShipAgent, ShipTask

# Build two specialised agents
researcher_agent = Agent.with_builtins(llm=llm, prompt="You are a senior researcher.")
writer_agent = Agent.with_builtins(llm=llm, prompt="You are a technical writer.")

# Wrap them as ShipAgents with persona metadata
researcher = ShipAgent(
    name="researcher",
    agent=researcher_agent,
    role="Senior Researcher",
    goal="Find comprehensive, accurate information",
)
writer = ShipAgent(
    name="writer",
    agent=writer_agent,
    role="Technical Writer",
    goal="Produce clear, well-structured reports",
)

# Define tasks with dependencies
crew = ShipCrew(
    name="research-crew",
    coordinator_llm=llm,
    agents=[researcher, writer],
    tasks=[
        ShipTask(
            name="research",
            description="Research {topic} thoroughly",
            agent="researcher",
            output_key="findings",
        ),
        ShipTask(
            name="write",
            description="Write a report using these findings: {findings}",
            agent="writer",
            depends_on=["research"],
        ),
    ],
)

result = crew.run(topic="AI agent architectures")
print(result.output)
```

## Task dependencies (DAG)

Tasks form a directed acyclic graph via `depends_on`. The coordinator resolves execution order using topological sort (Kahn's algorithm) and detects cycles before execution starts.

```python
# Diamond dependency pattern:
#   research
#   /      \
# analyze   summarize
#   \      /
#    report

tasks = [
    ShipTask(name="research", description="Research {topic}", agent="researcher"),
    ShipTask(
        name="analyze",
        description="Analyze findings: {research}",
        agent="analyst",
        depends_on=["research"],
    ),
    ShipTask(
        name="summarize",
        description="Summarize findings: {research}",
        agent="writer",
        depends_on=["research"],
    ),
    ShipTask(
        name="report",
        description="Combine analysis ({analyze}) and summary ({summarize})",
        agent="writer",
        depends_on=["analyze", "summarize"],
    ),
]
```

Template variables like `{research}` are automatically resolved from upstream task `output_key` values. By default, `output_key` equals the task name.

## Context variables

Runtime values are injected via keyword arguments to `crew.run()`. These fill `{placeholder}` tokens in task descriptions before execution.

```python
result = crew.run(
    topic="microservices",
    language="Python",
    audience="senior engineers",
)
```

Context variables and upstream output keys share the same template syntax. Context variables are resolved first; upstream outputs fill remaining placeholders as tasks complete.

## Three execution modes

### Sequential (default)

Tasks execute one at a time in topological order. Simplest mode -- good for debugging and cost-sensitive runs.

```python
crew = ShipCrew(
    name="seq-crew",
    coordinator_llm=llm,
    agents=[researcher, writer],
    tasks=tasks,
    process="sequential",
)
```

### Parallel

Independent tasks within each DAG layer run concurrently using `ThreadPoolExecutor`. Tasks in the same layer have no dependencies on each other, so they are safe to run at the same time.

```python
crew = ShipCrew(
    name="fast-crew",
    coordinator_llm=llm,
    agents=[researcher, analyst, writer],
    tasks=tasks,
    process="parallel",
)
# "analyze" and "summarize" run concurrently since both only depend on "research"
```

### Hierarchical

An LLM coordinator dynamically assigns tasks to agents, reviews outputs, and can request revisions before moving on. The coordinator sees all available agents, remaining tasks, and completed work each round.

```python
crew = ShipCrew(
    name="smart-crew",
    coordinator_llm=llm,
    agents=[researcher, analyst, writer],
    tasks=tasks,
    process="hierarchical",
    max_rounds=10,
)
```

In hierarchical mode, the coordinator LLM responds with JSON actions:

- `{"action": "assign", "task": "research", "agent": "researcher", "instructions": "..."}` -- assign a task
- `{"action": "revise", "task": "analyze", "agent": "analyst", "feedback": "..."}` -- request revision
- `{"action": "done", "summary": "..."}` -- mark the crew as finished

## ShipAgent

`ShipAgent` wraps any shipit_agent `Agent` with persona metadata. The persona (role, goal, backstory) is prepended to every task prompt so the agent stays in character.

```python
from shipit_agent.deep.ship_crew import ShipAgent

agent = ShipAgent(
    name="security-expert",
    agent=Agent.with_builtins(llm=llm, prompt="You are a security expert."),
    role="Security Auditor",
    goal="Identify and report security vulnerabilities",
    backstory="15 years of penetration testing experience.",
    capabilities=["code review", "OWASP analysis", "CVE lookup"],
)

# Direct execution (outside a crew)
result = agent.run("Audit the login module for SQL injection")
```

### ShipAgent fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique name within the crew |
| `agent` | `Agent` | The underlying shipit_agent `Agent` instance |
| `role` | `str` | Role description prepended to prompts |
| `goal` | `str` | Goal statement prepended to prompts |
| `backstory` | `str` | Background context prepended to prompts |
| `capabilities` | `list[str]` | What the agent can do (used in hierarchical mode) |

### ShipAgent.from_registry()

Build a `ShipAgent` directly from the built-in agent registry -- no manual `Agent` setup required.

```python
researcher = ShipAgent.from_registry("researcher", llm=llm)
auditor = ShipAgent.from_registry("security-auditor", llm=llm)

# With MCP servers
researcher = ShipAgent.from_registry(
    "researcher",
    llm=llm,
    mcps=[my_mcp_server],
)

# With overrides
custom = ShipAgent.from_registry(
    "code-reviewer",
    llm=llm,
    role="Python Code Reviewer",
    goal="Review Python code for PEP 8 compliance",
)
```

## ShipTask

A single unit of work in the DAG workflow.

### ShipTask fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Unique task name (also used as `output_key` if not set) |
| `description` | `str` | required | Task prompt with `{variable}` placeholders |
| `agent` | `str` | required | Name of the assigned `ShipAgent` |
| `depends_on` | `list[str]` | `[]` | Names of tasks that must complete first |
| `output_key` | `str` | `name` | Key under which the output is stored for downstream tasks |
| `output_schema` | `Any` | `None` | Optional schema for structured output validation |
| `max_retries` | `int` | `1` | Number of execution attempts on failure |
| `timeout_seconds` | `int` | `300` | Maximum wall-clock seconds per attempt |
| `context` | `dict` | `{}` | Extra key-value pairs appended to the prompt |

### Task with retries and timeout

```python
task = ShipTask(
    name="web-scrape",
    description="Scrape pricing data from {url}",
    agent="scraper",
    max_retries=3,
    timeout_seconds=120,
    context={"format": "JSON", "max_pages": "5"},
)
```

Context entries are appended as `Additional context:` lines in the prompt sent to the agent.

### Task serialization

```python
# To dict (for logging or persistence)
d = task.to_dict()

# From dict (for loading from JSON config)
restored = ShipTask.from_dict(d)
```

## create_ship_crew factory

A convenience function that accepts dicts or objects -- useful when loading crew configuration from JSON.

```python
from shipit_agent.deep.ship_crew import create_ship_crew

crew = create_ship_crew(
    coordinator_llm=llm,
    agents=[
        {"name": "researcher", "agent": r_agent, "role": "Researcher"},
        writer_ship_agent,  # already a ShipAgent
    ],
    tasks=[
        {"name": "research", "description": "Research {topic}", "agent": "researcher"},
        write_task,  # already a ShipTask
    ],
    process="parallel",
    name="mixed-crew",
)
```

## Validation

Call `crew.validate()` before execution to catch configuration errors early. It returns a list of human-readable error strings (empty means valid).

```python
errors = crew.validate()
if errors:
    for err in errors:
        print(f"Config error: {err}")
else:
    result = crew.run(topic="AI safety")
```

Checks performed:

- Every task references a registered agent name
- No cyclic dependencies in the task DAG
- Every `depends_on` entry names an existing task
- Template variable references are flagged if not produced by any upstream task

### Error types

| Exception | When raised |
|-----------|-------------|
| `CyclicDependencyError` | Task DAG contains a cycle (A depends on B, B depends on A) |
| `MissingAgentError` | A task references an agent name not registered in the crew |
| `TaskTimeoutError` | A task exceeds its `timeout_seconds` limit |
| `ShipCrewError` | Base class for all crew errors; also raised on general failures |

```python
from shipit_agent.deep.ship_crew.errors import (
    CyclicDependencyError,
    MissingAgentError,
    TaskTimeoutError,
    ShipCrewError,
)

try:
    result = crew.run(topic="AI agents")
except CyclicDependencyError as e:
    print(f"Fix your task graph: {e}")
except MissingAgentError as e:
    print(f"Register the agent first: {e}")
except TaskTimeoutError as e:
    print(f"Task took too long: {e}")
except ShipCrewError as e:
    print(f"Crew failed: {e}")
```

## ShipCrewResult

The result object returned by `crew.run()`.

| Field | Type | Description |
|-------|------|-------------|
| `output` | `str` | Final synthesized output (last task's result, or coordinator summary) |
| `task_results` | `dict[str, str]` | Per-task outputs keyed by `output_key` |
| `execution_order` | `list[str]` | Actual order tasks were executed |
| `total_tasks` | `int` | Total number of tasks in the crew |
| `failed_tasks` | `list[str]` | Names of tasks that failed |
| `metadata` | `dict` | Timing and other metadata (`elapsed_seconds`, etc.) |

```python
result = crew.run(topic="AI agents")

# Final output
print(result.output)

# Inspect individual task outputs
for key, value in result.task_results.items():
    print(f"\n--- {key} ---")
    print(value[:200])

# Execution metadata
print(f"Tasks: {result.total_tasks}")
print(f"Order: {result.execution_order}")
print(f"Failed: {result.failed_tasks}")
print(f"Time: {result.metadata['elapsed_seconds']}s")

# Serialize
d = result.to_dict()
```

## Streaming events

`crew.stream()` yields `AgentEvent` objects for each milestone during execution.

```python
for event in crew.stream(topic="AI agents"):
    print(f"[{event.type}] {event.message}")
```

Events emitted:

| Event type | When | Key payload fields |
|------------|------|-------------------|
| `run_started` | Crew begins execution | `process`, `tasks`, `agents` |
| `tool_called` | A task starts | `task`, `agent`, `description` |
| `tool_completed` | A task finishes successfully | `task`, `output_key`, `output` |
| `tool_failed` | A task fails | `task`, `error` |
| `run_completed` | Crew finishes | `output`, `execution_order`, `failed_tasks`, `elapsed_seconds` |

## Combining with CostTracker

Track costs across all agents in a multi-agent crew.

```python
from shipit_agent.costs import CostTracker, Budget

tracker = CostTracker(budget=Budget(max_dollars=10.00))
hooks = tracker.as_hooks()

# Attach hooks to each agent before wrapping in ShipAgent
r_agent = Agent.with_builtins(llm=llm, prompt="Researcher", hooks=hooks)
w_agent = Agent.with_builtins(llm=llm, prompt="Writer", hooks=hooks)

crew = ShipCrew(
    name="tracked-crew",
    coordinator_llm=llm,
    agents=[
        ShipAgent(name="researcher", agent=r_agent, role="Researcher"),
        ShipAgent(name="writer", agent=w_agent, role="Writer"),
    ],
    tasks=[
        ShipTask(name="research", description="Research {topic}", agent="researcher"),
        ShipTask(name="write", description="Write about {research}", agent="writer",
                 depends_on=["research"]),
    ],
)

result = crew.run(topic="quantum computing")

print(f"Total cost: ${tracker.total_cost:.4f}")
print(f"Calls: {len(tracker.breakdown())}")
```

## Full production example

```python
from shipit_agent import Agent
from shipit_agent.deep.ship_crew import ShipCrew, ShipAgent, ShipTask, create_ship_crew
from shipit_agent.deep.ship_crew.errors import ShipCrewError
from shipit_agent.costs import CostTracker, Budget

# Cost tracking with $5 budget
tracker = CostTracker(
    budget=Budget(max_dollars=5.00, warn_at=0.70),
    on_cost_alert=lambda spent, limit: print(f"Cost alert: ${spent:.2f}/${limit:.2f}"),
)

# Build agents from registry
researcher = ShipAgent.from_registry("researcher", llm=llm)
writer = ShipAgent.from_registry("blog-writer", llm=llm)
reviewer = ShipAgent.from_registry("code-reviewer", llm=llm)

# Configure the crew
crew = ShipCrew(
    name="content-pipeline",
    coordinator_llm=llm,
    agents=[researcher, writer, reviewer],
    tasks=[
        ShipTask(
            name="research",
            description="Research {topic} with focus on practical examples",
            agent=researcher.name,
            output_key="findings",
            max_retries=2,
        ),
        ShipTask(
            name="draft",
            description="Write a blog post about {topic} using: {findings}",
            agent=writer.name,
            depends_on=["research"],
            output_key="draft",
        ),
        ShipTask(
            name="review",
            description="Review this draft for technical accuracy: {draft}",
            agent=reviewer.name,
            depends_on=["draft"],
            output_key="review",
            timeout_seconds=120,
        ),
    ],
    process="sequential",
    verbose=True,
)

# Validate before running
errors = crew.validate()
if errors:
    raise ValueError(f"Crew config errors: {errors}")

# Execute with streaming
try:
    for event in crew.stream(topic="building AI agents with Python"):
        print(f"[{event.type}] {event.message}")
except ShipCrewError as e:
    print(f"Crew failed: {e}")

print(f"\nTotal cost: ${tracker.total_cost:.4f}")
```

## Using plain Agent (without builtins)

ShipAgents can wrap any `Agent` — with or without built-in tools.

```python
from shipit_agent import Agent
from shipit_agent.deep.ship_crew import ShipCrew, ShipAgent, ShipTask

# Plain agents — no built-in tools, just LLM + prompt
researcher = ShipAgent(
    name="researcher",
    agent=Agent(llm=llm, prompt="You research topics thoroughly."),
    role="Researcher",
)

writer = ShipAgent(
    name="writer",
    agent=Agent(llm=llm, prompt="You write clear, concise summaries."),
    role="Writer",
)

crew = ShipCrew(
    name="simple-crew",
    coordinator_llm=llm,
    agents=[researcher, writer],
    tasks=[
        ShipTask(name="research", description="Research {topic}", agent="researcher", output_key="findings"),
        ShipTask(name="write", description="Summarize: {findings}", agent="writer", depends_on=["research"]),
    ],
)

result = crew.run(topic="serverless computing trends")
print(result.output)
```

## Wrapping a DeepAgent in ShipCrew

```python
from shipit_agent.deep import DeepAgent

# DeepAgent as a crew member — gets planning, verification, and reflection
deep_researcher = DeepAgent.with_builtins(
    llm=llm,
    prompt="You are a thorough researcher with deep analysis capabilities.",
    verify=True,
)

crew = ShipCrew(
    name="deep-crew",
    coordinator_llm=llm,
    agents=[
        ShipAgent(name="deep-researcher", agent=deep_researcher.agent, role="Deep Researcher"),
        writer,
    ],
    tasks=[
        ShipTask(name="research", description="Deep research on {topic}", agent="deep-researcher", output_key="findings"),
        ShipTask(name="write", description="Write report from: {findings}", agent="writer", depends_on=["research"]),
    ],
)

result = crew.run(topic="AI safety in autonomous agents")
```

## Detailed streaming with payload inspection

```python
crew = ShipCrew(
    name="stream-detail",
    coordinator_llm=llm,
    agents=[researcher, writer],
    tasks=[
        ShipTask(name="research", description="Research Python async patterns", agent="researcher", output_key="findings"),
        ShipTask(name="write", description="Summarize: {findings}", agent="writer", depends_on=["research"]),
    ],
)

for event in crew.stream():
    if event.type == "run_started":
        print(f"🚀 Crew started | mode: {event.payload.get('process')} | tasks: {event.payload.get('tasks')}")
    elif event.type == "tool_called":
        print(f"⚙️  Task '{event.payload.get('task')}' started → agent: {event.payload.get('agent')}")
    elif event.type == "tool_completed":
        print(f"✅ Task '{event.payload.get('task')}' done | output_key: {event.payload.get('output_key')}")
        print(f"   Preview: {event.payload.get('output', '')[:150]}...")
    elif event.type == "tool_failed":
        print(f"❌ Task '{event.payload.get('task')}' FAILED: {event.payload.get('error')}")
    elif event.type == "run_completed":
        print(f"🏁 Crew completed in {event.payload.get('elapsed_seconds')}s")
        print(f"   Order: {event.payload.get('execution_order')}")
        print(f"   Failed: {event.payload.get('failed_tasks')}")
        print(f"   Output: {event.payload.get('output', '')[:200]}")
```

## API reference

| Method / Class | Description |
|----------------|-------------|
| `ShipCrew(name, coordinator_llm, agents, tasks, process, ...)` | Create a crew with named agents and tasks |
| `crew.run(**context_vars)` | Execute and return `ShipCrewResult` |
| `crew.stream(**context_vars)` | Execute and yield `AgentEvent` objects |
| `crew.validate()` | Check configuration, return list of error strings |
| `crew.add_agent(agent)` | Add a `ShipAgent` to the crew |
| `crew.add_task(task)` | Add a `ShipTask` to the workflow |
| `create_ship_crew(coordinator_llm, agents, tasks, ...)` | Factory accepting dicts or objects |
| `ShipAgent(name, agent, role, goal, ...)` | Named agent with persona metadata |
| `ShipAgent.from_registry(agent_id, llm, ...)` | Build from the built-in agent registry |
| `ShipAgent.run(prompt)` | Execute a task directly |
| `ShipAgent.stream(prompt)` | Execute a task and yield events |
| `ShipTask(name, description, agent, ...)` | A single unit of work in the DAG |
| `ShipTask.from_dict(data)` | Deserialize from dict |
| `ShipTask.to_dict()` | Serialize to dict |
| `ShipTask.resolve_description(outputs)` | Fill `{var}` placeholders from upstream outputs |
| `ShipCrewResult.output` | Final synthesized text |
| `ShipCrewResult.task_results` | Per-task outputs keyed by `output_key` |
| `ShipCrewResult.to_dict()` | Serialize the full result |
