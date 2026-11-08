---
title: Observability exports
description: Stream AgentEvent traces out of shipit-agent into LangSmith or any OpenTelemetry backend. Batching, attribute mapping, and silent-failure semantics explained.
---

# Observability exports

Every agent, autopilot, and crew in shipit-agent already emits a
stream of `AgentEvent` records into the configured `TraceStore`. Two
ready-made exporters let you forward that same stream to an external
observability backend without touching your agent code:

| Exporter | Class | Backend | Transport |
| --- | --- | --- | --- |
| LangSmith | `LangSmithExporter` | LangSmith runs API | `urllib` POST, batched |
| OpenTelemetry | `OpenTelemetryExporter` | Any OTLP collector / Jaeger / Tempo / Honeycomb / Datadog | `opentelemetry-api` / `opentelemetry-sdk` |

Both implement the same `TraceStore` protocol (`append_event`,
`load`) so they slot into the runtime identically and can be layered
behind a fan-out store if you want both.

## Choosing an exporter

**Pick `LangSmithExporter` when:**

- Your team already runs LangSmith for LLM eval / replay and you want
  shipit traces showing up in the same project.
- You want zero extra dependencies — the exporter uses stdlib
  `urllib.request`, no LangSmith SDK required.
- You're fine with a 20-span / 2-second batched POST to the public
  API.

**Pick `OpenTelemetryExporter` when:**

- You already pipe OTLP to Jaeger, Tempo, Honeycomb, Datadog, New
  Relic, or a self-hosted collector.
- You want span attributes, correlated trace IDs, and multi-service
  stitching (e.g. agent span → downstream HTTP client span).
- You're happy to install `opentelemetry-api` + `opentelemetry-sdk`
  and wire up your own processor / exporter pair.

Both exporters **never raise** from `append_event`. Transport errors
are logged at `WARNING` via the standard `logging` module and the
event is dropped — tracing must not be allowed to take a production
agent down.

---

## LangSmith

Translates each `AgentEvent` into a LangSmith **run** record and
POSTs batches to `${api_url}/runs`.

### Setup

```bash
export LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxxxxxx
```

```python
from shipit_agent.tracing_exporters.langsmith_exporter import LangSmithExporter

exporter = LangSmithExporter(
    api_key=None,                                 # defaults to LANGCHAIN_API_KEY env
    api_url="https://api.smith.langchain.com",    # override for self-hosted
    project="shipit-agent",
    timeout_seconds=5.0,
    batch_size=20,                                # flush after 20 events
    flush_interval_seconds=2.0,                   # or 2 seconds, whichever first
)
```

### Example — wire into an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.tracing_exporters.langsmith_exporter import LangSmithExporter

exporter = LangSmithExporter(project="shipit-agent/prod")

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-5.5"),
    trace_store=exporter,
)
agent.run("Why is the sky blue?")
exporter.flush()       # force the last partial batch out before shutdown
```

### Batching behaviour

A batch is flushed when **either** of these fires, whichever comes
first:

- The buffer reaches `batch_size` events (default **20**).
- `flush_interval_seconds` have elapsed **since the first event in
  the current buffer** (default **2.0 s**) — measured against
  `time.monotonic()`, not wall clock.

Call `exporter.flush()` explicitly at shutdown; the exporter has no
background thread, so a small tail of events can linger in the buffer
until the next `append_event` triggers a time-based flush.

If `api_key` is `None` (env var also missing), `flush()` logs a
`WARNING` with the dropped count and continues — the agent keeps
running.

### Attribute mapping

Each `AgentEvent` becomes:

```text
{
  "name": event.type,
  "run_type": "chain",
  "inputs":  {"message": event.message},
  "outputs": <event.payload, coerced to JSON-plain>,
  "start_time": <now UTC ISO8601>,
  "end_time":   <now UTC ISO8601>,      # same as start — events are point-in-time
  "extra": {
    "trace_id": <trace_id from append_event>,
    "project":  <exporter.project>,
    "metadata": <append_event metadata arg, JSON-plain>,
  },
}
```

Dataclasses are converted with `asdict`, tuples become lists, and
anything that isn't `str/int/float/bool/None` falls back to
`str(value)` so no event shape can break the POST.

### Transport failures

`urllib.error.URLError`, `OSError`, and `TimeoutError` on the POST
are caught and logged at `WARNING` as
`"LangSmithExporter failed to post N run(s) to <url>: <exc>"`. The
batch is dropped — no retry queue. If you need durable guarantees,
layer the exporter behind a persistent `TraceStore` and treat
LangSmith as the best-effort mirror.

---

## OpenTelemetry

Emits each `AgentEvent` as an OTel span on a provided (or default)
tracer provider.

### Setup

```bash
pip install opentelemetry-api opentelemetry-sdk
# plus whatever exporter you actually use, e.g.
pip install opentelemetry-exporter-otlp
```

The `opentelemetry` package is imported **lazily inside
`__init__`** — it's required at instantiation time, not at module
import. If the packages aren't installed, the exporter raises
`RuntimeError("Install opentelemetry-api and opentelemetry-sdk.")`.

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider(resource=Resource.create({"service.name": "shipit-agent"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint="https://otlp.example.com/v1/traces",
)))
trace.set_tracer_provider(provider)

from shipit_agent.tracing_exporters.otel_exporter import OpenTelemetryExporter

otel = OpenTelemetryExporter(
    service_name="shipit-agent",
    tracer_provider=provider,       # optional — falls back to the global one
)
```

### Example — wire into an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-5.5"),
    trace_store=otel,
)
agent.run("Summarise the latest release notes.")
# spans flow into your OTLP collector via the BatchSpanProcessor
```

### Span lifecycle

Because the `AgentEvent` handed to `append_event` is already
finalised, each span is **started and ended inside the same call** —
there are no context-manager handoffs. That means span duration is
effectively zero; these are event-style spans, not duration spans.
If you need duration correlation, drive it from your downstream HTTP
client spans (which OTel propagates via the trace context).

### Attribute mapping

Span name: `"agent.<event.type>"`.

Attributes set on every span:

| Attribute | Source |
| --- | --- |
| `shipit.trace_id` | `trace_id` arg to `append_event` |
| `shipit.event.type` | `event.type` |
| `shipit.event.message` | `event.message` |
| `shipit.payload.<key>` | each entry in `event.payload` (except `events`) |
| `shipit.metadata.<key>` | each entry in the `metadata` arg |

If `event.payload["events"]` is a list of dicts, each is added as a
nested **span event** via `span.add_event(name, attributes=...)`.
`name` is taken from `sub["name"]` or `sub["type"]` (falling back to
`"event"`), and the remaining keys are namespaced as
`shipit.event.<k>`.

### Attribute coercion

OTel only accepts `str / bool / int / float` (or homogeneous
sequences of same) as attribute values. Anything else is coerced:

- Lists / tuples of primitives → passed through as a list.
- Mixed-type lists → `[str(v) for v in value]`.
- Anything else → `repr(value)`.

This means no payload shape can make `append_event` raise — worst
case you get a stringified attribute.

### Transport failures

OpenTelemetry transport errors are handled **by your configured
span processor / exporter**, not by this class. If the OTLP endpoint
is down, the SDK's `BatchSpanProcessor` queues and retries per its
own policy; shipit-agent is unaware. Configure the processor's
queue / timeout / retry knobs for your durability requirements.

---

## Layering both

If you want LangSmith for human eval **and** OTel for infra
correlation at the same time, wrap both behind a fan-out store:

```python
class FanOutStore:
    def __init__(self, *stores):
        self._stores = stores
    def append_event(self, trace_id, event, metadata=None):
        for s in self._stores:
            s.append_event(trace_id, event, metadata)
    def load(self, trace_id):
        return None

agent = Agent(llm=..., trace_store=FanOutStore(langsmith, otel))
```

## Langfuse — v2 AND v3 servers

Two complementary layers; use either or both.

### Layer 1 — LLM calls via litellm callbacks (`LiteLLMChatLLM` / `BedrockChatLLM`)

`LiteLLMChatLLM` calls `litellm.completion()` directly, so litellm's Langfuse
callbacks trace every LLM call automatically. **Pick the callback that matches
your Langfuse SERVER version** — this is the part that bites people:

```python
import os, litellm

os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
os.environ["LANGFUSE_HOST"] = "https://my-langfuse.example.com"

# Langfuse server v3.x  →  use the OTel integration (native OTLP ingest)
litellm.callbacks = ["langfuse_otel"]

# Langfuse server v2.x  →  use the classic integration (v2 SDK, .trace() API)
# litellm.success_callback = ["langfuse"]
# litellm.failure_callback = ["langfuse"]
```

!!! warning "v2 SDK ↔ v3 server = HTTP 500"
    The classic `"langfuse"` callback uses the **v2 SDK** (`pip install
    "langfuse<3"`); its payloads make a **v3 server return 500** on real
    traces. Against a v3 server always use `"langfuse_otel"` — it sends
    OpenTelemetry to `/api/public/otel`, which v3 ingests natively and
    needs no `langfuse` SDK at all.

```python
from shipit_agent import Agent
from shipit_agent.llms import BedrockChatLLM

agent = Agent.for_role(
    "finance-analyst",
    llm=BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0"),
)
agent.run("Close Q2.")          # every LLM call now lands in Langfuse
```

Caveat: Gemma 4 on Bedrock routes through the OpenAI SDK (mantle endpoint),
not litellm — those calls bypass litellm callbacks. Layer 2 covers them.

### Layer 2 — full agent traces via `LangfuseExporter` (works with ANY adapter)

The built-in exporter ships the **whole agent run** — a root trace plus one
child span per tool call (real durations, inputs, outputs, ✗ error status) —
and speaks **both server generations** with zero SDK dependency:

```python
from shipit_agent import Agent
from shipit_agent.tracing_exporters import LangfuseExporter

agent = Agent.with_builtins(
    llm=llm,                              # any provider — Gemma-mantle included
    trace_store=LangfuseExporter(
        host="https://my-langfuse.example.com",   # keys from LANGFUSE_* env
        api_version="auto",               # "auto" | "v2" | "v3"
    ),
)
```

- `api_version="auto"` (default) probes `/api/public/health` once and picks
  the wire format from the reported server version.
- **v3 servers** get OTLP/JSON at `/api/public/otel/v1/traces`.
- **v2 servers** get the classic batch API at `/api/public/ingestion`.
- Transport failures are logged and **never break the agent run**.

Common production setup: litellm callback for token/cost analytics **plus**
`LangfuseExporter` for step-level agent debugging — they land in the same
Langfuse project.

## Built-in run metrics

Before reaching for an exporter, two zero-setup options cover the common
cases. Every event carries a `timestamp`, tool events carry `duration_ms`
and a `call_id`, and the result aggregates them:

```python
result = agent.run("...")
print(result.summary())
# {"duration_seconds": 3.4, "iterations": 2, "tool_calls": 3,
#  "tool_failures": 0, "usage": {"input_tokens": 812, "output_tokens": 240},
#  "tools": {"bash": {"calls": 2, "failures": 0, "total_ms": 2140.0}}}

from shipit_agent import format_activity
print(format_activity(result))   # human-readable tool cards + footer
```

## Related

- [Streaming events](../agent/streaming.md) — the same event stream, but live
  at the SDK boundary.
- [Cost tracking](cost-tracking.md) — pair trace export with per-call
  dollar accounting.
- [Tracing (agent)](../agent/tracing.md) — the in-process
  `TraceStore` contract these exporters implement.
- [Event types reference](../reference/events.md) — every
  `AgentEvent.type` and its payload shape.
