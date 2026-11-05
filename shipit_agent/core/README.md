# `shipit_agent.core`

The run loop and the values that move through it.

| Module | What it does |
|---|---|
| `agent_mixin.py` | Adding the new machinery to the existing ``Agent`` without replacing it |
| `async_runtime.py` | The awaitable agent loop |
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
| `runtime.py` | The synchronous agent loop |
| `runtime_core.py` | The parts of the agent loop that are the same whether you await or not |
| `state.py` | Per-run state and safe shared-state isolation for tool execution |
| `structured.py` | Helpers for structured output: detect pydantic models, build the response format and parse the model's answer |
| `structured_output.py` | Structured output orchestrator — the public API for v1.0.8 |
| `tool_runner.py` | Executing tool calls: argument checks, safe event metadata and collected results |
| `tools_compat.py` | A one-function bridge to the host's tool output type |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
