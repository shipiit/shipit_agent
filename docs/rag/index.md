# Super RAG

A powerful, pluggable retrieval-augmented-generation subsystem built into
`shipit_agent`. Index documents, run hybrid search (vector + BM25 + RRF),
optionally rerank with an LLM, and plug the whole thing into any `Agent`
or deep agent with a single `rag=` parameter.

> **TL;DR** — `rag = RAG.default(embedder=llm); agent = Agent(llm=llm, rag=rag)`.
> Every chunk the agent retrieves shows up in `result.rag_sources` with stable
> `[1]`, `[2]`, … citation indices.

---

## What you get

| Feature | Out of the box |
| --- | --- |
| **Sentence-aware chunker** | Onyx-style title prefix + metadata suffix, character-overlap support |
| **Hybrid search** | Vector + BM25 in parallel, fused with Reciprocal Rank Fusion |
| **Reranking** | LLM-as-judge default; pluggable Cohere / cross-encoder backends |
| **Recency bias** | Exponential decay over `created_at` timestamps |
| **Context expansion** | Pull `chunks_above` / `chunks_below` neighbours into hits |
| **Filters** | By document ids, sources, metadata fields, and time windows |
| **Source tracking** | Per-run `[N]` citation tracker, attached to `AgentResult.rag_sources` |
| **Pluggable backends** | `VectorStore` / `KeywordStore` / `Embedder` / `Reranker` protocols |
| **Zero required deps** | Works out of the box with stdlib + numpy-free pure-Python defaults |
| **DRK_CACHE adapter** | Read existing pgvector indexes through `DrkCacheVectorStore` |

---

## Architecture

```
shipit_agent/rag/
├── types.py             Document, Chunk, SearchQuery, SearchResult,
│                        IndexFilters, RAGContext, RAGSource
├── chunker.py           DocumentChunker (sentence-aware, title prefix,
│                        metadata suffix)
├── embedder.py          Embedder protocol + HashingEmbedder, CallableEmbedder
├── vector_store.py      VectorStore protocol + InMemoryVectorStore
├── keyword_store.py     KeywordStore protocol + InMemoryBM25Store
├── reranker.py          Reranker protocol + LLMReranker
├── search_pipeline.py   HybridSearchPipeline (vector + keyword + RRF +
│                        recency bias + rerank + context expansion)
├── extractors.py        TextExtractor (TXT/MD/HTML always; PDF/DOCX lazy)
├── rag.py               RAG facade — index/search/fetch_chunk + source tracking
├── tools.py             rag_search, rag_fetch_chunk, rag_list_sources
└── adapters/
    └── drk_cache.py     Read existing DRK_CACHE pgvector indexes
```

The `RAG` facade is the only thing most users touch. Everything below it is
swappable through plain Python protocols.

---

## Five-line quickstart

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_text("Shipit supports Python 3.10+.", source="readme.md")
agent = Agent(llm=my_llm, rag=rag)

result = agent.run("What Python version does Shipit support?")
print(result.output)         # "Shipit supports Python 3.10+. [1]"
for s in result.rag_sources:
    print(f"[{s.index}] {s.source}: {s.text}")
```

That is the entire flow:

1. Build a `RAG` (vector + keyword + chunker + embedder, all wired up).
2. Index text or files.
3. Pass `rag=` to any `Agent` constructor.
4. Read sources off `AgentResult.rag_sources`.

---

## What's next

- **[Standalone RAG](standalone.md)** — indexing and searching without an agent.
- **[RAG + Agent](with-agent.md)** — wiring `rag=` into a regular `Agent`.
- **[RAG + Deep Agents](with-deep-agents.md)** — `GoalAgent`, `ReflectiveAgent`,
  `Supervisor`, `AdaptiveAgent`, `PersistentAgent`.
- **[Adapters](adapters.md)** — `DrkCacheVectorStore` and other production backends.
- **[API reference](api.md)** — every public class and method.

Notebook tour:

- `notebooks/22_rag_basics.ipynb` — standalone RAG
- `notebooks/23_rag_with_agent.ipynb` — `Agent` integration
- `notebooks/24_rag_with_deep_agents.ipynb` — every deep-agent pattern
