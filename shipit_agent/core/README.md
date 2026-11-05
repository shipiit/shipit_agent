# `shipit_agent.core`

The run loop and the values that move through it.

| Module | What it does |
|---|---|
| `agent_mixin.py` | Adding the new machinery to the existing ``Agent`` without replacing it |
| `async_runtime.py` | The agent loop: construction, events, `run()` and `stream()`; the phases live in `loop/` |
| `bridge.py` | Letting the existing ``Agent`` drive the new run loop |
| `checkpoint.py` | Enough state to stop a run and start it again somewhere else |
| `construction.py` | Building the tool registry for a run and the schemas sent to the model |
| `exceptions.py` | Exceptions raised by shipit-agent itself |
| `graph.py` | The run loop, as an explicit graph that yields everything as it happens |
| `models.py` | The values that move through a run |
| `narration.py` | Small, factual helpers used to narrate runtime progress |
| `packets.py` | Serialising run events and results for HTTP, WebSocket and SSE clients |
| `policies.py` | Retry and model-routing policies for a run |
| `reasoning.py` | Structured reasoning runs: decompose a problem, weigh options and synthesise evidence with the reasoning tools |
| `registry.py` | The set of tools a run can call, including tools discovered from MCP servers |
| `runtime.py` | The synchronous face of the one loop: `run()` and `stream()` that block |
| `runtime_core.py` | The loop's synchronous decisions, assembled from the mixins in `decisions/` |
| `state.py` | Per-run state and safe shared-state isolation for tool execution |
| `structured.py` | Helpers for structured output: detect pydantic models, build the response format and parse the model's answer |
| `structured_output.py` | Structured output orchestrator — the public API for v1.0.8 |
| `tool_runner.py` | Executing tool calls: argument checks, safe event metadata and collected results |
| `tools_compat.py` | A one-function bridge to the host's tool output type |

## `loop/` — one turn, phase by phase

| Module | What it does |
|---|---|
| `turn.py` | The `Turn` passed between the phases |
| `turn_setup.py` | Hooks and guardrails, tools, system prompt, prior history |
| `turn_steps.py` | Call the model, step by step, until it answers |
| `answer_step.py` | A step that ends in an answer: required tools, the verify gate, stop hooks |
| `tool_step.py` | A step that runs tools: one group, parallel when read-only |
| `tool_exec.py` | One tool call through every gate |
| `turn_finish.py` | Settle the answer, save the session, report |
| `model_call.py` | Calling the model, with retries and backoff |
| `step_narration.py` | The one-line progress notes |
| `planning.py` | Planning first when the router asks |
| `code_mode.py` | Code mode: one script that calls the tools |
| `event_stream.py` | `stream()`: events as they happen |

## `decisions/` — what the loop decides, without awaiting

| Module | What it does |
|---|---|
| `requested_tools.py` | Tools the user asked for by name |
| `tool_calls.py` | Call ids, argument checks, duplicates, parallel safety |
| `step_messages.py` | What the model is sent each step |
| `tool_deferral.py` | Deferred tool loading |
| `guardrail_checks.py` | Guardrails on input, answer and tool results |
| `permission_gate.py` | Whether a call may run; lockdown |
| `response_checks.py` | Repairing tool calls, nudges, stop hooks |
| `usage_budget.py` | Token and cost tracking, budgets |
| `context_fit.py` | Compaction and request fitting |
| `shared_tool_state.py` | State shared by a turn's tool calls |
| `run_wrap_up.py` | Run summary and cleanup |
| `artifact_paths.py`, `prior_outputs.py`, `call_keys.py` | Helpers the decisions share |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
