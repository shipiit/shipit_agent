# RAG + Agent

Wire the Super RAG subsystem into a regular `shipit_agent.Agent` using
**one constructor parameter**: `rag=`. The agent gains three new tools
(`rag_search`, `rag_fetch_chunk`, `rag_list_sources`) and the system
prompt is augmented with citation instructions automatically.

After every `agent.run(...)` the result carries a `rag_sources` field —
the DRK_CACHE-style citation panel.

---

## Quickstart

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_text("Shipit supports Python 3.10+.", source="readme.md")
rag.index_text("Agents stream events in real time.", source="streaming.md")

agent = Agent(llm=my_llm, rag=rag)
result = agent.run("What Python version does Shipit support?")

print(result.output)
# "Shipit supports Python 3.10+. [1]"

for src in result.rag_sources:
    print(f"[{src.index}] {src.source} (chunk {src.chunk_id}, score {src.score:.2f})")
    print(f"    {src.text}")
```

---

## What `rag=` actually does

When you construct an `Agent` with `rag=...`, the constructor:

1. **Auto-appends three tools** — `rag_search`, `rag_fetch_chunk`,
   `rag_list_sources` — to `agent.tools`. If you already supplied a
   tool with the same name, the existing one wins (no duplication).
2. **Augments the system prompt** with a short instruction block telling
   the LLM how to use the tools and how to cite sources with `[N]`
   markers. The block is appended to whatever prompt you passed in.
3. **Wraps `run` and `stream`** in `rag.begin_run()` / `rag.end_run()`
   so every chunk retrieved during the run is captured by a per-run
   `SourceTracker`.

After the run completes, the captured sources are deduplicated by
`chunk_id`, indexed with stable `[1]`, `[2]`, … citation numbers, and
attached to `result.rag_sources` as a list of `RAGSource` dataclasses.

---

## Inspecting the wiring

```python
agent = Agent(llm=my_llm, rag=rag)

# Three tools auto-wired
print([t.name for t in agent.tools])
# ['rag_search', 'rag_fetch_chunk', 'rag_list_sources']

# Prompt was augmented
print("rag_search" in agent.prompt)  # True
```

---

## Citation panel

```python
result = agent.run("Tell me about Python support and streaming")

print(result.output)
# "Shipit supports Python 3.10+. Agents also stream events. [1][2]"

for s in result.rag_sources:
    print(f"[{s.index}] {s.source}")
    print(f"    chunk_id={s.chunk_id}")
    print(f"    score={s.score:.2f}")
    print(f"    text={s.text}")
```

`RAGSource` fields:

| Field | Type | Description |
| --- | --- | --- |
| `index` | `int` | `[1]`, `[2]`, … citation marker |
| `chunk_id` | `str` | Identifier of the underlying chunk |
| `document_id` | `str` | Parent document id |
| `text` | `str` | Chunk text (for rendering in the UI) |
| `score` | `float` | Final fused relevance score |
| `source` | `str \| None` | File path / URL / source label |
| `metadata` | `dict` | Pass-through chunk metadata |

`RAGSource` has a `to_dict()` helper for JSON serialization.

---

## Streaming with sources

`agent.stream(...)` yields events as they happen. RAG-equipped runs emit
a final `rag_sources` event after the run completes with the consolidated
list of citations:

```python
for event in agent.stream("What Python version?"):
    print(f"[{event.type}] {event.message}")
    if event.type == "rag_sources":
        for src in event.payload["sources"]:
            print(f"  [{src['index']}] {src['source']}")
```

---

## With `Agent.with_builtins`

The full built-in tool catalogue (web search, code execution, file
workspace, …) coexists with the RAG tools — just pass `rag=` to
`with_builtins`:

```python
agent = Agent.with_builtins(llm=my_llm, rag=rag)
```

---

## Multiple agents sharing one `RAG`

A single `RAG` instance is reusable across many `Agent`s. The internal
source tracker uses thread-local state so concurrent runs on different
threads don't bleed citations into each other:

```python
researcher = Agent(llm=my_llm, prompt="You research the codebase.", rag=rag)
writer     = Agent(llm=my_llm, prompt="You write user-facing docs.", rag=rag)

result_a = researcher.run("Find sources about streaming")
result_b = writer.run("Draft a release note about Python support")

# Each result has its own independent rag_sources list.
```

---

## Customising the prompt section

If you need to override the auto-injected RAG prompt section (for
example, to translate it or to enforce a different citation style),
override `RAG.prompt_section()`:

```python
class MyRAG(RAG):
    def prompt_section(self) -> str:
        return (
            "You may call rag_search, rag_fetch_chunk, and rag_list_sources. "
            "Cite results with `(source: chunk_id)` markers."
        )

rag = MyRAG.default(embedder=my_embedder)
agent = Agent(llm=my_llm, rag=rag)
```

---

## Disabling auto-wiring

If you want fine-grained control — for example to wire only `rag_search`
and skip `rag_fetch_chunk` — build the tools manually and pass them to
`tools=` instead of using `rag=`:

```python
from shipit_agent.rag.tools import RAGSearchTool

agent = Agent(
    llm=my_llm,
    tools=[RAGSearchTool(rag=rag)],
    # Don't pass rag= here, so the prompt isn't auto-augmented.
)
```

In this mode `result.rag_sources` will still be empty — source tracking
only runs when the `Agent` knows about the `RAG` via the `rag=` field.
You can call `rag.begin_run()` / `rag.end_run()` manually around your
own loop to capture sources without the auto-wiring.

---

## See also

- [Standalone RAG](standalone.md) — indexing and searching without an agent
- [RAG + Deep Agents](with-deep-agents.md) — `GoalAgent`, `Supervisor`, …
- [API reference](api.md) — every public class and method
- Notebook: `notebooks/23_rag_with_agent.ipynb`
