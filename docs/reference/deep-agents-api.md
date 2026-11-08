# Deep Agents API Reference

Complete API reference for all deep agent classes, their parameters, methods, return types, and factory methods.

---

## GoalAgent

Autonomous agent that decomposes goals into sub-tasks and tracks progress against success criteria.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | LLM adapter |
| `tools` | `None` | Custom tools |
| `mcps` | `None` | MCP servers |
| `goal` | required | Goal with criteria |
| `use_builtins` | `False` | Attach every built-in tool |
| `prompt` | see code | System prompt for inner agent |
| `memory` | `None` | Memory for the inner agent |
| `rag` | `None` | A RAG the agent cites from |
| `**agent_kwargs` | | Passed to the inner Agent |

### Factory

`GoalAgent.with_builtins()` builds the agent with every built-in tool attached:

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `goal` | required | The goal and its success criteria |
| `mcps` | `None` | MCP servers |
| `rag` | `None` | A RAG the agent cites from |
| `**kwargs` | | Passed to the inner Agent |

### Methods

| Method | Returns | Description |
|---|---|---|
| `run()` | `GoalResult` | Execute goal synchronously |
| `stream()` | `Iterator[AgentEvent]` | Execute with real-time event streaming |

### GoalResult

| Field | Type | Description |
|---|---|---|
| `goal` | `Goal` | The original goal |
| `output` | `str` | Final output text |
| `goal_status` | `str` | `"completed"`, `"partial"`, or `"failed"` |
| `criteria_met` | `list[bool]` | Per-criterion pass/fail |
| `steps_taken` | `int` | Number of steps executed |
| `step_outputs` | `list[dict]` | Per-step task and output |

### Goal

| Field | Type | Default | Description |
|---|---|---|---|
| `objective` | `str` | required | What to achieve |
| `success_criteria` | `list[str]` | `[]` | How to measure success |
| `max_steps` | `int` | `20` | Maximum sub-tasks |

### Stream events

| Event | When |
|---|---|
| `run_started` | Goal execution begins |
| `planning_started` | Decomposing goal into sub-tasks |
| `planning_completed` | Sub-tasks ready (payload: `subtasks`) |
| `step_started` | Starting a sub-task |
| `tool_called` / `tool_completed` | Inner agent tool usage |
| `run_completed` | Goal finished (payload: `status`, `criteria_met`) |

---

## ReflectiveAgent

Agent that produces output, reflects critically, and revises until quality threshold is met.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `tools` | `None` | Custom tools |
| `mcps` | `None` | MCP servers |
| `reflection_prompt` | see code | What the critique checks |
| `max_reflections` | `3` | Critique rounds at most |
| `quality_threshold` | `0.8` | Score that ends the loop |
| `use_builtins` | `False` | Attach every built-in tool |
| `prompt` | `'You are a helpful assistant.'` | System prompt for the inner agent |
| `memory` | `None` | Memory for the inner agent |
| `**agent_kwargs` | | Passed to the inner Agent |

### Factory

`ReflectiveAgent.with_builtins()` builds the agent with every built-in tool attached:

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `mcps` | `None` | MCP servers |
| `**kwargs` | | Passed to the inner Agent |

### Methods

| Method | Returns | Description |
|---|---|---|
| `run(task: str)` | `ReflectionResult` | Execute with reflection loop |
| `stream(task: str)` | `Iterator[AgentEvent]` | Execute with real-time streaming |

### ReflectionResult

| Field | Type | Description |
|---|---|---|
| `output` | `str` | Final revised output |
| `reflections` | `list[Reflection]` | Each reflection's feedback + score |
| `revisions` | `list[str]` | Each version of the output |
| `final_quality` | `float` | Last quality score (0.0-1.0) |
| `iterations` | `int` | Number of reflection cycles |

### Reflection

| Field | Type |
|---|---|
| `feedback` | `str` |
| `quality_score` | `float` |
| `revision_needed` | `bool` |

### Stream events

| Event | When |
|---|---|
| `run_started` | Task begins |
| `step_started` | Generating output or revising |
| `reasoning_started` | Starting a reflection |
| `reasoning_completed` | Reflection done (payload: `quality`, `feedback`) |
| `run_completed` | Threshold met or max reflections reached |

---

## AdaptiveAgent

Agent that can create new tools at runtime from Python code.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `tools` | `None` | Custom tools |
| `mcps` | `None` | MCP servers |
| `can_create_tools` | `True` | Let the agent write new tools at run time |
| `sandbox` | `True` | Run tools the agent creates in a sandbox |
| `use_builtins` | `False` | Attach every built-in tool |
| `prompt` | `'You are a helpful assistant.'` | System prompt for the inner agent |
| `**agent_kwargs` | | Passed to the inner Agent |

### Factory

`AdaptiveAgent.with_builtins()` builds the agent with every built-in tool attached:

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `mcps` | `None` | MCP servers |
| `**kwargs` | | Passed to the inner Agent |

### Methods

| Method | Returns | Description |
|---|---|---|
| `create_tool(name, description, code)` | `FunctionTool` | Create and register a new tool |
| `run(task: str)` | `AgentResult` | Execute with all tools |
| `stream(task: str)` | `Iterator[AgentEvent]` | Execute with streaming |

### Properties

| Property | Type | Description |
|---|---|---|
| `created_tools` | `list[CreatedTool]` | Record of all dynamically created tools |
| `tools` | `list[Tool]` | All available tools (including created) |

---

## Supervisor

Hierarchical agent that plans, delegates to workers, reviews quality, and combines results.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `workers` | required | The workers to delegate to |
| `strategy` | `'plan_and_delegate'` | How the supervisor delegates |
| `allow_parallel` | `False` | Run independent delegations at once |
| `max_delegations` | `15` | Delegations before it stops |
| `rag` | `None` | A RAG the agent cites from |
| `**agent_kwargs` | | Passed to the inner Agent |

### Factory

`Supervisor.with_builtins()` builds the agent with every built-in tool attached:

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `worker_configs` | required | [{"name": "...", "prompt": "...", "capabilities": [...]}] |
| `mcps` | `None` | MCP servers |
| `rag` | `None` | A RAG the agent cites from |
| `**kwargs` | | Passed to the inner Agent |

### Methods

| Method | Returns | Description |
|---|---|---|
| `run(task: str)` | `SupervisorResult` | Execute with delegation loop |
| `stream(task: str)` | `Iterator[AgentEvent]` | Execute with real-time streaming |

### Worker

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Worker identifier |
| `agent` | `Agent` | The agent that does the work |
| `capabilities` | `list[str]` | What this worker can do |

### SupervisorResult

| Field | Type | Description |
|---|---|---|
| `output` | `str` | Final combined output |
| `delegations` | `list[Delegation]` | Round-by-round history |
| `total_rounds` | `int` | How many rounds were used |

### Stream events

| Event | When |
|---|---|
| `run_started` | Supervisor begins (payload: `workers`) |
| `planning_started` | Deciding next delegation |
| `tool_called` | Delegating to worker (payload: `worker`, `task`) |
| `tool_completed` | Worker finished (payload: `worker`, `output`) |
| `tool_failed` | Unknown worker requested |
| `run_completed` | Task complete or max rounds |

---

## PersistentAgent

Agent with checkpoint/resume capability for long-running tasks.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `llm` | required | The model adapter |
| `tools` | `None` | Custom tools |
| `checkpoint_dir` | `'.shipit_checkpoints'` | Where checkpoints are saved |
| `checkpoint_interval` | `5` | Steps between checkpoints |
| `max_steps` | `50` | Steps before the run stops |
| `rag` | `None` | A RAG the agent cites from |
| `**agent_kwargs` | | Passed to the inner Agent |

### Methods

| Method | Returns | Description |
|---|---|---|
| `run(task, *, agent_id)` | `AgentResult` | Execute with periodic checkpointing |
| `resume(agent_id)` | `AgentResult` | Resume from last checkpoint |
| `status(agent_id)` | `dict` | Check progress (`"paused"` or `"not_found"`) |

---

## Channel

Typed communication channel for agent-to-agent message passing.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `name` | `'default'` | Channel name |

### Methods

| Method | Returns | Description |
|---|---|---|
| `send(message)` | `None` | Send to target agent's queue |
| `receive(*, agent, timeout=None)` | `AgentMessage \| None` | Get next message (FIFO) |
| `ack(message)` | `None` | Mark message as acknowledged |
| `history()` | `list[AgentMessage]` | All sent messages |
| `pending(*, agent)` | `int` | Count unread messages |

### AgentMessage

| Field | Type | Description |
|---|---|---|
| `from_agent` | `str` | Sender name |
| `to_agent` | `str` | Receiver name |
| `type` | `str` | Message type (e.g. `"research_complete"`) |
| `data` | `dict` | Structured payload |
| `requires_ack` | `bool` | Whether ack is expected |
| `acknowledged` | `bool` | Whether ack was received |

---

## AgentBenchmark

Systematic testing framework for agents.

### Constructor

| Parameter | Default | Description |
| :- | :- | :- |
| `name` | required | The benchmark name |
| `cases` | required | The test cases to run |

### TestCase

| Field | Type | Default | Description |
|---|---|---|---|
| `input` | `str` | required | Prompt to send to agent |
| `expected_contains` | `list[str]` | `[]` | Output must contain these |
| `expected_not_contains` | `list[str]` | `[]` | Output must NOT contain these |
| `expected_tools` | `list[str]` | `[]` | These tools must be used |
| `max_iterations` | `int` | `10` | Max allowed iterations |

### Methods

| Method | Returns | Description |
|---|---|---|
| `run(agent)` | `BenchmarkReport` | Run all test cases |

### BenchmarkReport

| Property | Type | Description |
|---|---|---|
| `passed` | `int` | Count of passing tests |
| `failed` | `int` | Count of failing tests |
| `total` | `int` | Total test count |
| `pass_rate` | `float` | Ratio (0.0 - 1.0) |
| `summary()` | `str` | Human-readable report |
| `to_dict()` | `dict` | JSON-serializable export |
