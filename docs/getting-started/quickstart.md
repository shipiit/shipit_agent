# Quick Start

Get a working agent — and a deep agent, and a RAG-grounded agent — in
five minutes.

---

## 1. Install

Pick the install that matches what you want to do:

```bash
# Just an agent with one LLM provider
pip install 'shipit-agent[openai]'

# An agent + the full Super RAG stack (embeddings, vector stores, PDF, …)
pip install 'shipit-agent[openai,rag]'

# Everything (every LLM provider, RAG, browser tools)
pip install 'shipit-agent[all]'
```

The base library has zero required dependencies beyond `pydantic`. All
provider SDKs and RAG backends are opt-in extras.

---

## 2. Set your API key

Create `.env` in your project root:

```bash
SHIPIT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
SHIPIT_OPENAI_MODEL=gpt-4o-mini
```

`build_llm_from_env()` reads this and gives you a ready-to-use LLM
client. Switch providers later by changing one line — see step 6.

---

## 3. Your first Agent

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env()             # reads SHIPIT_LLM_PROVIDER from .env
agent = Agent.with_builtins(llm=llm)   # web_search, open_url, tool_search, …

result = agent.run("Find today's Bitcoin price in USD from a reputable source.")
print(result.output)
```

That's a complete tool-using agent — `with_builtins` ships ~30 tools
out of the box (web search, browser, code execution, file workspace,
Slack, Gmail, Jira, Linear, Notion, …).

### Stream events instead

Replace `agent.run(...)` with `agent.stream(...)` to watch each step
happen live:

```python
for event in agent.stream("Find today's Bitcoin price in USD."):
    print(f"{event.type:20s} {event.message}")
```

You'll see:

```
run_started          Agent run started
step_started         LLM completion started
reasoning_started    🧠 Model reasoning started
reasoning_completed  🧠 Model reasoning completed
tool_called          Tool called: web_search
tool_completed       Tool completed: web_search
step_started         LLM completion started
tool_called          Tool called: open_url
tool_completed       Tool completed: open_url
run_completed        Agent run completed
```

Every event is yielded **the instant it happens**, not buffered until
the end. Your UI can render a live "Thinking" panel, a tool call log,
and a final answer — all incrementally.

---

## 4. Your first Deep Agent

Deep agents add planning, self-evaluation, reflection, supervision, and
checkpointing on top of `Agent`. The simplest one is `GoalAgent` — give
it a goal and success criteria, and it decomposes the work into ordered
sub-tasks, runs each through an inner `Agent`, and self-evaluates after
every step.

```python
from shipit_agent.deep import Goal, GoalAgent

goal_agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Find Bitcoin's current price and 24h change, then summarise",
        success_criteria=[
            "Includes current USD price",
            "Includes 24h percent change",
            "Cites the data source",
        ],
    ),
)

result = goal_agent.run()
print(result.goal_status)   # "completed" | "partial" | "failed"
print(result.criteria_met)  # [True, True, True]
print(result.output)
```

Stream a deep agent the same way you'd stream a regular `Agent`:

```python
for event in goal_agent.stream():
    print(f"[{event.type}] {event.message}")
```

Other deep agents follow the same shape:

| Pattern | Use it for |
| --- | --- |
| `GoalAgent` | "I have a goal with success criteria" |
| `ReflectiveAgent` | "Generate, critique, revise until quality threshold" |
| `Supervisor` | "Coordinate multiple worker agents on parts of a task" |
| `AdaptiveAgent` | "Let the agent write new tools at runtime" |
| `PersistentAgent` | "Long-running task that needs to survive crashes" |

See the [Deep Agents](../deep-agents/index.md) docs for the full tour.

---

## 5. Your first Agent with Super RAG

Plug a knowledge base into any agent with **one constructor parameter**:
`rag=`.

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG, HashingEmbedder

# Build a RAG (in-memory hybrid index — vector + BM25 + RRF)
rag = RAG.default(embedder=HashingEmbedder(dimension=512))

# Index whatever you have — text, files, or pre-built Documents.
rag.index_text(
    "Shipit supports Python 3.10 and newer.",
    source="readme.md",
)
rag.index_file("docs/manual.pdf")     # PDF needs `pip install shipit-agent[rag-pdf]`
rag.index_file("docs/installation.md")

# Wire RAG into the agent — auto-appends rag_search, rag_fetch_chunk,
# rag_list_sources tools and augments the system prompt with citation
# instructions.
agent = Agent.with_builtins(llm=llm, rag=rag)

result = agent.run("What Python version does Shipit support?")
print(result.output)
# "Shipit supports Python 3.10+. [1]"

# DRK_CACHE-style citation panel — every chunk the agent retrieved.
for src in result.rag_sources:
    print(f"[{src.index}] {src.source} (chunk {src.chunk_id}, score {src.score:.2f})")
    print(f"    {src.text}")
```

That's the entire flow:

1. `RAG.default(embedder=...)` — a fully wired hybrid index in one line.
2. `rag.index_text(...)` / `rag.index_file(...)` — index anything.
3. `Agent(..., rag=rag)` — agent gains 3 new tools and a citation prompt.
4. `result.rag_sources` — automatic deduplicated `[N]` citation list.

### Production embedder

`HashingEmbedder` is stdlib-only and good for tests. In production
swap it for a real embedder — pass any object with an `embed(texts)`
method, or wrap a function:

```python
from openai import OpenAI
from shipit_agent.rag import CallableEmbedder, RAG

client = OpenAI()

def embed(texts):
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in resp.data]

rag = RAG.default(embedder=CallableEmbedder(fn=embed, dimension=1536))
```

### RAG with a deep agent

Every deep agent accepts the **same** `rag=` parameter:

```python
from shipit_agent.deep import Goal, GoalAgent

goal_agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Write release notes from the changelog",
        success_criteria=["Mentions deep agents", "Mentions structured output"],
    ),
    rag=rag,                # ← same parameter as Agent
)

result = goal_agent.run()
# Every step of the goal-decomposition loop has rag_search wired in.
```

`GoalAgent`, `ReflectiveAgent`, `AdaptiveAgent`, `Supervisor`, and
`PersistentAgent` all forward `rag=` to the inner `Agent` they build.
For `Supervisor.with_builtins(..., rag=rag)` the same RAG is wired into
**every worker** so a researcher and a writer can cite the same
sources.

See the full Super RAG section:

- [Overview](../rag/index.md)
- [Standalone RAG](../rag/standalone.md) — index/search without an agent
- [Files, Chunks & Sources](../rag/files-and-chunks.md) — PDF/MD ingest, persisting chunks, what `source` means
- [RAG + Agent](../rag/with-agent.md)
- [RAG + Deep Agents](../rag/with-deep-agents.md)
- [Adapters](../rag/adapters.md) — Chroma, Qdrant, pgvector, DRK_CACHE
- [API reference](../rag/api.md)

---

## 6. Switch providers

Change one line in `.env`:

```bash
SHIPIT_LLM_PROVIDER=bedrock     # or anthropic, gemini, groq, together, ollama, openai
```

Restart, re-run. **No code change.** Credentials are loaded from
whichever env vars the provider needs (`AWS_REGION_NAME`,
`ANTHROPIC_API_KEY`, etc.) — `build_llm_from_env` raises a clear error
if any are missing.

---

## Next

- **Streaming** — [Streaming guide](../guides/streaming.md): understand all 15 event types (including the new `rag_sources`)
- **Reasoning** — [Reasoning & thinking](../guides/reasoning.md): render thinking panels from model reasoning blocks
- **Tools** — [Tool search](../guides/tool-search.md): let the agent discover its own tools
- **Custom tools** — [Custom tools](../guides/custom-tools.md): build a new tool from scratch
- **Deep agents** — [Deep Agents overview](../deep-agents/index.md): goal, reflective, supervisor, adaptive, persistent
- **Super RAG** — [Super RAG overview](../rag/index.md): grounded answers with citations in one parameter
