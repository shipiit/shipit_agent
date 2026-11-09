# Deployment

An agent is a Python object, so it deploys like any Python service. This page covers serving one over HTTP, packaging it in a container, the limits to set before it faces real users, and keeping state when you run several copies.

---

## Serve an agent over HTTP

`shipit serve` puts an agent behind an OpenAI-compatible API, so any OpenAI SDK or chat UI can call it:

```bash
pip install "shipit-agent[anthropic]"
export SHIPIT_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...
shipit serve --port 8399 --api-key "$(openssl rand -hex 16)"
```

| Endpoint | What it returns |
| --- | --- |
| `POST /v1/chat/completions` | An OpenAI chat completion; with `"stream": true`, OpenAI-style chunks, plus a `shipit` key on tool and usage events |
| `POST /v1/stream` | Every agent event as Server-Sent Events, for a client that draws the whole run |
| `GET /v1/models` | The served model id (`--name`, default `shipit`) |
| `GET /health` | `{"status": "ok"}` and the process's stream generation |

`--api-key` (or `SHIPIT_API_KEY`) makes every request send `Authorization: Bearer <key>`. Without one the server is open, which is only safe on `127.0.0.1`, its default host. `--provider`, `--model`, `--project-root`, `--role`, `--guardrails` and `--mcp` configure the agent it serves.

!!! warning "One agent, one conversation"
    `shipit serve` serves a single `Agent`, and an agent carries earlier turns into its next run. Every caller therefore shares one conversation, and one caller's questions are sent to the model along with the next caller's. That suits a personal server. For several users, give each request its own agent, as below.

### One agent per request

`AgentServer` calls `stream()` and `run()` on whatever it is given, so an object that builds a fresh agent for each call keeps every request separate:

```python
from shipit_agent import Agent
from shipit_agent.cli.serve import AgentServer
from shipit_agent.llms import build_llm_from_env


class FreshAgent:
    """Builds a new agent for every request, so no conversation is shared."""

    def build(self) -> Agent:
        return Agent.with_builtins(llm=build_llm_from_env(), project_root="/srv/workspace", max_budget_usd=0.50)

    def stream(self, prompt: str):
        yield from self.build().stream(prompt)

    def run(self, prompt: str):
        return self.build().run(prompt)


AgentServer(FreshAgent(), api_key="change-me").serve_forever(host="0.0.0.0", port=8399)
```

The server is `ThreadingHTTPServer`: each request runs on its own thread. Shared objects you hand every agent, such as a `RAG` index or a `CostTracker`, must be safe to use from several threads; a `RAG` index is, because it tracks each run's sources separately.

---

## Inside your own web app

In FastAPI, Django or Flask, build the agent in the request handler and return its result or its event stream. `agent.stream_sse()` yields ready-made Server-Sent Events:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

app = FastAPI()


@app.post("/run")
def run(prompt: str) -> dict[str, str]:
    agent = Agent.with_builtins(llm=build_llm_from_env(), project_root="/srv/workspace")
    return {"output": agent.run(prompt).output}


@app.post("/stream")
def stream(prompt: str) -> StreamingResponse:
    agent = Agent.with_builtins(llm=build_llm_from_env(), project_root="/srv/workspace")
    return StreamingResponse(agent.stream_sse(prompt), media_type="text/event-stream")
```

The handlers are plain `def`, so FastAPI runs them on its thread pool and a long run does not block the event loop. For `async def` handlers use `agent.arun()` and `agent.astream()`; see [Async runtime](async-runtime.md).

---

## In a container

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir "shipit-agent[anthropic]"
WORKDIR /srv/workspace

EXPOSE 8399
CMD ["sh", "-c", "shipit serve --host 0.0.0.0 --port 8399 --api-key \"$SHIPIT_API_KEY\""]
```

```bash
docker build -t my-agent .
docker run -p 8399:8399 \
  -e SHIPIT_LLM_PROVIDER=anthropic -e ANTHROPIC_API_KEY -e SHIPIT_API_KEY \
  my-agent
```

Listening on `0.0.0.0` exposes the server beyond the container, so set `SHIPIT_API_KEY`. Pass credentials with `-e` or your platform's secret store, never baked into the image.

---

## Configuration

`build_llm_from_env()` and `shipit serve` read the model from the environment:

| Variable | What it sets |
| --- | --- |
| `SHIPIT_LLM_PROVIDER` | The provider: `anthropic`, `openai`, `bedrock`, `gemini`, `vertex`, `groq`, `ollama`, `litellm` and [more](../getting-started/environment.md). Default `bedrock`. |
| `SHIPIT_<PROVIDER>_MODEL` | The model for that provider, for example `SHIPIT_ANTHROPIC_MODEL=claude-sonnet-5-5`. |
| The provider's own keys | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_REGION_NAME` with AWS credentials, and so on. |
| `SHIPIT_API_KEY` | The Bearer key `shipit serve` requires. |

Limits and safety are set on the agent, not in the environment:

| Agent parameter | Use it to |
| --- | --- |
| `max_budget_usd` | Stop a run that has spent this much. |
| `max_turns` (or `max_iterations`) | Cap the model calls in one run. |
| `permissions`, `permission_mode` | Decide which tool calls run, ask or are refused. See [Permissions](permissions.md). |
| `project_root` | The folder file tools may touch. |

To run shell commands in an OS sandbox that can write only in the project, with the network off, use the Agent SDK API: `AgentOptions(sandbox={"enabled": True})`. See [Sandbox](sandbox.md).

---

## Running several copies

Each request builds its own agent, so copies of the service need nothing shared to answer. What does need sharing is anything an agent should remember between requests:

- **Sessions** that resume a conversation: `FileSessionStore` on a shared volume, or your own class with `load(session_id)`, `save(record)` and `list_all()`. Pass it as `session_store=`.
- **Memory** that outlives a conversation: `FileMemoryStore` on a shared volume, or your own class with `add(fact)` and `search(query, limit)`. Pass it as `memory_store=`.

See [Sessions](../agent/sessions.md) and [Advanced memory](advanced-memory.md).

---

## Monitoring

Every event is a plain object; `to_dict()` gives its `type`, `message`, `payload` and `timestamp` (Unix seconds), ready for a structured log:

```python
import json
import logging

from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

logger = logging.getLogger("agent")
agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")

for event in agent.stream("Summarise the open issues"):
    if event.type in {"tool_called", "tool_failed", "run_completed", "run_failed"}:
        logger.info(json.dumps(event.to_dict(), default=str))
```

To count spend, attach a `CostTracker`; with a `Budget` it also stops runs that go over:

```python
from shipit_agent import Agent
from shipit_agent.costs import Budget, CostTracker
from shipit_agent.llms import build_llm_from_env

tracker = CostTracker(budget=Budget(max_dollars=5.00))
agent = Agent.with_builtins(llm=build_llm_from_env(), hooks=tracker.as_hooks())
agent.run("Review the last commit")
tokens = tracker.total_tokens
print(f"${tracker.total_cost:.4f}, {tokens['input_tokens']} in, {tokens['output_tokens']} out")
```

[Cost tracking](cost-tracking.md) covers budgets and pricing; [Observability exports](observability-exports.md) sends traces to OpenTelemetry and similar.

---

## Before you go live

- Credentials come from the environment or a secret store, never from code or the image.
- The server needs a key (`SHIPIT_API_KEY`) whenever it listens beyond `127.0.0.1`.
- Each user's request gets its own agent, or users share one conversation.
- `max_budget_usd` and `max_turns` bound what one request can spend.
- `permissions`, `project_root` and the sandbox bound what one request can change.
- Logs skip prompts and tool output that may hold users' data.
- A proxy in front rate-limits each client.

---

## Next steps

- [Error recovery](error-recovery.md): retries, fallbacks and failed tools
- [Hooks](hooks.md): run your code before and after model and tool calls
- [Async runtime](async-runtime.md): `arun()` and `astream()` for async servers
