# Deployment Guide

Deploy SHIPIT Agent to production with confidence. This guide covers containerization, scaling, monitoring, and best practices for running agents in production environments.

---

## Docker Deployment

The simplest production deployment uses Docker:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "shipit_agent.server"]
```

```bash
docker build -t shipit-agent .
docker run -p 8000:8000 --env-file .env shipit-agent
```

---

## Environment Variables

Production environments should set these variables:

| Variable | Required | Description |
|---|:---:|---|
| `SHIPIT_LLM_PROVIDER` | ✅ | LLM provider (`openai`, `anthropic`, `bedrock`, etc.) |
| `SHIPIT_LOG_LEVEL` | ❌ | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `SHIPIT_MAX_ITERATIONS` | ❌ | Safety limit for agent loops (default: 25) |
| `SHIPIT_TIMEOUT_SECONDS` | ❌ | Per-run timeout (default: 300) |
| `SHIPIT_MEMORY_BACKEND` | ❌ | Memory storage (`file`, `redis`, `postgres`) |

Provider-specific keys (e.g., `OPENAI_API_KEY`, `AWS_REGION_NAME`) are also required depending on your chosen provider.

---

## FastAPI Integration

Run agents behind a production-grade API:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

app = FastAPI()
llm = build_llm_from_env()

@app.post("/run")
async def run_agent(prompt: str):
    agent = Agent.with_builtins(llm=llm)
    result = agent.run(prompt)
    return {"output": result.output, "steps": result.step_count}

@app.post("/stream")
async def stream_agent(prompt: str):
    agent = Agent.with_builtins(llm=llm)

    async def generate():
        for event in agent.stream(prompt):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## Scaling Considerations

### Horizontal Scaling

Each agent run is stateless by default. Scale horizontally by running multiple instances behind a load balancer:

```yaml
# docker-compose.yml
services:
  agent:
    image: shipit-agent
    deploy:
      replicas: 4
    environment:
      - SHIPIT_LLM_PROVIDER=bedrock
      - AWS_REGION_NAME=us-east-1
```

### Memory and State

With several replicas, sessions and memory must live outside the process. `FileSessionStore` and `FileMemoryStore` work on a shared volume. For a database, implement the store interfaces: a `SessionStore` has `load(session_id)`, `save(record)` and `list_all()`, and a `MemoryStore` has `add(fact)` and `search(query)`. Pass yours as `session_store=` and `memory_store=`.

### Rate Limiting

Use hooks to enforce rate limits per user or API key:

```python
from shipit_agent import AgentHooks

hooks = AgentHooks()

@hooks.on_before_llm
def rate_limit(context):
    if context.metadata.get("calls_this_minute", 0) > 60:
        raise RateLimitError("Too many requests")
```

---

## Monitoring

### Structured Logging

Every agent event is a structured object. Pipe events to your observability stack:

```python
import json
import logging

logger = logging.getLogger("shipit")

for event in agent.stream(prompt):
    logger.info(json.dumps({
        "type": event.type,
        "message": event.message,
        "timestamp": event.timestamp.isoformat(),
        "step": event.step_number,
    }))
```

### Cost Tracking

Use the `on_after_llm` hook to track token usage and costs:

```python
@hooks.on_after_llm
def track_cost(context, response):
    tokens = response.usage
    cost = calculate_cost(tokens, context.llm.model)
    metrics.increment("llm_cost", cost)
    metrics.increment("llm_tokens", tokens.total)
```

---

## Security Checklist

Before deploying to production:

- [ ] API keys are stored in environment variables, never in code
- [ ] Agent timeout is configured (`SHIPIT_TIMEOUT_SECONDS`)
- [ ] Max iterations are limited (`SHIPIT_MAX_ITERATIONS`)
- [ ] Tool permissions are explicitly configured
- [ ] File system access is sandboxed (if using file tools)
- [ ] Network access is restricted to required domains
- [ ] Logging does not capture sensitive user data
- [ ] Rate limiting is enabled for public-facing endpoints

---

## Next Steps

- [Error Recovery](error-recovery.md) — handle failures gracefully in production
- [Hooks & Middleware](hooks.md) — add monitoring, rate limiting, and guardrails
- [Async Runtime](async-runtime.md) — use with FastAPI and modern async Python
