# RAG + Deep Agents

Every deep-agent pattern in `shipit_agent.deep` accepts the **same**
`rag=` parameter as `Agent`. They forward it to every inner `Agent`
they build, so every step of a multi-step agentic workflow has access
to the knowledge base — and every chunk it retrieves shows up in the
final `rag_sources` panel.

| Deep agent | `rag=` support | Forwarded to |
| --- | --- | --- |
| `GoalAgent` | ✅ explicit param | the inner `Agent` built per sub-task |
| `ReflectiveAgent` | ✅ via `**agent_kwargs` | the inner `Agent` built per generation |
| `AdaptiveAgent` | ✅ via `**agent_kwargs` | the inner `Agent` (alongside dynamic tools) |
| `Supervisor` | ✅ explicit param | every worker `Agent` in `with_builtins` |
| `PersistentAgent` | ✅ explicit param | every checkpointed inner `Agent` |

The DX rule of thumb: **if you can pass `rag=` to `Agent`, you can pass
it to any deep agent the same way.**

---

## GoalAgent

Decomposes a goal into ordered sub-tasks and runs each through an inner
`Agent`. With `rag=` set, every sub-task can call `rag_search` to
ground its answer.

```python
from shipit_agent.deep import Goal, GoalAgent
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/release_notes_1.0.2.md")

goal_agent = GoalAgent(
    llm=my_llm,
    goal=Goal(
        objective="Write a 1-page summary of release 1.0.2",
        success_criteria=[
            "Mentions deep agents",
            "Mentions structured output",
            "Mentions teams and pipelines",
        ],
    ),
    rag=rag,
)

result = goal_agent.run()
```

`GoalAgent` exposes `rag` as a first-class constructor parameter and
forwards it into every inner `Agent` it builds.

---

## ReflectiveAgent

Generates an answer, critiques it, and revises if needed. Pass `rag=`
the same way:

```python
from shipit_agent.deep import ReflectiveAgent

agent = ReflectiveAgent(
    llm=my_llm,
    reflection_prompt="Check for accuracy, completeness, and citation quality.",
    rag=rag,
)
result = agent.run("Write a section about streaming events.")
```

`rag=` is captured via `**agent_kwargs` and forwarded to every inner
`Agent` build call. The critique step can also call `rag_search` to
verify facts before signing off.

---

## AdaptiveAgent

Can write new tools at runtime *and* use RAG for grounding:

```python
from shipit_agent.deep import AdaptiveAgent

agent = AdaptiveAgent(
    llm=my_llm,
    can_create_tools=True,
    rag=rag,
)
result = agent.run(
    "Parse the CSV at /data/sales.csv and answer questions using our docs."
)
```

The runtime tool factory does **not** know about the RAG instance — but
because `rag=` is forwarded into the inner `Agent`, every dynamic tool
runs in the same context as the RAG tools and shares the same source
tracker.

---

## Supervisor — one shared knowledge base for the team

`Supervisor.with_builtins(..., rag=rag)` wires the *same* RAG into every
worker agent. A researcher and a writer can both retrieve from — and
cite — the same chunks:

```python
from shipit_agent.deep import Supervisor

supervisor = Supervisor.with_builtins(
    llm=my_llm,
    worker_configs=[
        {"name": "researcher", "prompt": "You research the codebase."},
        {"name": "writer", "prompt": "You write user-facing answers."},
    ],
    rag=rag,
)
result = supervisor.run("Draft a release blog post about deep agents.")
```

If you build the workers manually instead of using `with_builtins`,
just construct each worker's `Agent` with `rag=rag` directly:

```python
from shipit_agent import Agent
from shipit_agent.deep import Supervisor, Worker

researcher_agent = Agent(llm=my_llm, prompt="Research mode.", rag=rag)
writer_agent     = Agent(llm=my_llm, prompt="Writer mode.",   rag=rag)

supervisor = Supervisor(
    llm=my_llm,
    workers=[
        Worker(name="researcher", agent=researcher_agent),
        Worker(name="writer",     agent=writer_agent),
    ],
    rag=rag,  # Optional but recommended — keeps the citation panel working.
)
```

The `Supervisor` itself stores `rag` on the instance and adds it to
`agent_kwargs`, so callers can introspect what's wired up.

---

## PersistentAgent

Checkpoints long runs to disk and forwards `rag=` to every inner
`Agent` it builds. RAG state survives across resumes because the chunks
live in the store, not in the checkpoint:

```python
from shipit_agent.deep import PersistentAgent

agent = PersistentAgent(
    llm=my_llm,
    checkpoint_dir="./checkpoints",
    checkpoint_interval=5,
    rag=rag,
)

# Initial run — checkpointed every 5 steps.
agent.run("A long research task", agent_id="task-1")

# After a crash / restart, resume:
agent.resume(agent_id="task-1")
```

---

## Source tracking across the team

Whatever pattern you pick, every chunk retrieved during the run flows
back into the same `rag_sources` panel — even when multiple worker
agents share the same `RAG`. The source tracker is per-run, not
per-agent, so:

- `Agent.run` → `result.rag_sources` reflects that single run.
- `Supervisor.run` (when using `with_builtins(..., rag=rag)`) → every
  worker contributes to the same panel; the supervisor's final result
  surfaces all of them.

This is the same UX you get from DRK_CACHE: a single answer plus a
single deduplicated panel of `[N]` citations.

---

## See also

- [Standalone RAG](standalone.md) — indexing and searching without an agent
- [RAG + Agent](with-agent.md) — the basic agent integration
- [API reference](api.md) — every public class and method
- Notebook: `notebooks/24_rag_with_deep_agents.ipynb`
