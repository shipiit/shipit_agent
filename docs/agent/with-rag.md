---
title: Agent — With RAG
description: Plug the Super RAG subsystem into a plain shipit_agent.Agent with one parameter and read DRK_CACHE-style citations off result.rag_sources.
---

# Agent — With RAG

Wire a knowledge base into a plain `Agent` using one constructor
parameter: `rag=`. The agent gains three new tools (`rag_search`,
`rag_fetch_chunk`, `rag_list_sources`) and the system prompt is
augmented with citation instructions automatically.

After every `agent.run(...)` the result carries a `rag_sources` field
— the DRK_CACHE-style citation panel.

> Want the full Super RAG documentation? See
> [Super RAG → Overview](../rag/index.md), the
> [Standalone RAG cookbook](../rag/standalone.md), and the
> [Files, Chunks & Sources](../rag/files-and-chunks.md) guide.

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
   markers.
3. **Wraps `run` and `stream`** in `rag.begin_run()` /
   `rag.end_run()` so every chunk retrieved during the run is captured
   by a per-run `SourceTracker`.

After the run completes, the captured sources are deduplicated by
`chunk_id`, indexed with stable `[1]`, `[2]`, … citation numbers, and
attached to `result.rag_sources` as a list of `RAGSource` dataclasses.

---

## Indexing files (PDF, MD, HTML, …)

```python
rag.index_file("docs/manual.pdf")        # needs `pip install shipit-agent[rag-pdf]`
rag.index_file("docs/install.md")        # zero deps
rag.index_file("docs/architecture.html") # zero deps
```

For an in-depth recipe (chunk size tuning, persisting chunks to disk,
reloading them later) see
[Files, Chunks & Sources](../rag/files-and-chunks.md).

---

## Streaming with sources

`agent.stream(...)` yields events as they happen. RAG-equipped runs
emit a final `rag_sources` event with the consolidated citation list:

```python
for event in agent.stream("How do I configure logging?"):
    if event.type == "rag_sources":
        for src in event.payload["sources"]:
            print(f"  [{src['index']}] {src['source']}")
    elif event.type == "run_completed":
        print(event.payload.get("output"))
```

---

## Multiple agents sharing one `RAG`

```python
researcher = Agent(llm=llm, prompt="You research the codebase.", rag=rag)
writer     = Agent(llm=llm, prompt="You write user-facing copy.",  rag=rag)
```

The internal source tracker uses **thread-local state** so concurrent
runs on different threads don't bleed citations into each other. Each
agent's `result.rag_sources` is independent.

---

## Customising the auto-injected prompt section

```python
class MyRAG(RAG):
    def prompt_section(self) -> str:
        return (
            "You may call rag_search, rag_fetch_chunk, and rag_list_sources. "
            "Cite results with `(source: chunk_id)` markers."
        )

agent = Agent(llm=llm, rag=MyRAG.default(embedder=embedder))
```

---

## Disabling auto-wiring

If you want fine-grained control — for example to wire only
`rag_search` and skip `rag_fetch_chunk` — build the tools manually and
pass them to `tools=` instead of using `rag=`:

```python
from shipit_agent.rag.tools import RAGSearchTool

agent = Agent(
    llm=llm,
    tools=[RAGSearchTool(rag=rag)],
    # Don't pass rag= here, so the prompt isn't auto-augmented.
)
```

In this mode `result.rag_sources` will still be empty — source tracking
only runs when the `Agent` knows about the `RAG` via the `rag=` field.
Call `rag.begin_run()` / `rag.end_run()` manually around your own loop
to capture sources without the auto-wiring.

---

## See also

- [Super RAG overview](../rag/index.md)
- [Standalone RAG](../rag/standalone.md)
- [Files, Chunks & Sources](../rag/files-and-chunks.md)
- [RAG + Agent (full guide)](../rag/with-agent.md)
- [RAG + Deep Agents](../rag/with-deep-agents.md)
- [Parameters Reference](../reference/parameters.md#rag)
