# Standalone RAG (no agent)

The `shipit_agent.rag` package is fully usable without ever touching an
`Agent`. This page covers the indexing and retrieval surface in detail.

---

## Building a `RAG`

The fastest path is `RAG.default(embedder=...)`, which gives you an
in-memory hybrid index (vector + BM25) with sensible defaults:

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
```

For a fully custom setup, build the pieces explicitly:

```python
from shipit_agent.rag import (
    RAG, DocumentChunker, HashingEmbedder,
    InMemoryBM25Store, InMemoryVectorStore,
)

rag = RAG(
    vector_store=InMemoryVectorStore(),
    keyword_store=InMemoryBM25Store(k1=1.2, b=0.75),
    embedder=HashingEmbedder(dimension=384),
    chunker=DocumentChunker(target_tokens=256, overlap_tokens=32),
)
```

Anything implementing the `VectorStore` / `KeywordStore` / `Embedder`
protocols can be dropped in. See [Adapters](adapters.md) for production
backends.

---

## Indexing

### From a string

```python
rag.index_text(
    "Shipit supports Python 3.10 and newer.",
    source="readme.md",
    metadata={"tags": ["install", "python"]},
)
```

By default `index_text` assigns a fresh UUID as the `document_id`. Pass
`document_id=` explicitly when you want a stable identity (so a later
`reindex` or `delete_document` can find it):

```python
rag.index_text("Hello", document_id="hello", source="hello.md")
rag.index_text("Hello v2", document_id="hello", source="hello.md")  # replaces
```

### From a file

```python
rag.index_file("docs/manual.pdf")
```

`index_file` extracts text via the built-in `TextExtractor`:

| Format | Backend | Dependency |
| --- | --- | --- |
| `.txt`, `.md`, `.markdown`, `.log` | stdlib | none |
| `.csv`, `.json` | stdlib | none |
| `.html`, `.htm` | stdlib `html.parser` | none |
| `.pdf` | `pypdf` | `pip install pypdf` |
| `.docx` | `python-docx` | `pip install python-docx` |

Unknown extensions fall back to UTF-8 plaintext.

### From a `Document`

For full control over the metadata + title:

```python
from shipit_agent.rag import Document
from datetime import datetime, timezone

rag.index_document(Document(
    id="release-1.0.2",
    content="...",
    title="Release Notes 1.0.2",
    source="changelog.md",
    metadata={"tags": ["release"]},
    created_at=datetime.now(tz=timezone.utc),
))
```

### Bulk indexing

```python
rag.index_documents([doc1, doc2, doc3])
```

### Re-indexing & deletion

```python
rag.reindex("release-1.0.2", content="updated body")
rag.delete_document("release-1.0.2")
```

---

## Searching

### Hybrid search

```python
ctx = rag.search("how do I stream events from an agent?", top_k=3)

print(ctx.total_found, ctx.timing_ms)
for r in ctx.results:
    print(r.score, r.chunk.source, r.chunk.text)
```

`ctx` is a `RAGContext`. The most useful field is `ctx.results` —
a list of `SearchResult`, each carrying:

- `chunk` — the `Chunk` itself
- `score` — final fused score
- `vector_score` / `keyword_score` — per-branch raw scores
- `rerank_score` — set when reranking is enabled
- `expanded_above` / `expanded_below` — neighbouring chunks (when
  `chunks_above` / `chunks_below` are set)

### Prompt-ready output

```python
print(ctx.to_prompt_context(max_chars=4000))
```

Renders as:

```
[1] source=readme.md | chunk_id=readme::0
    Shipit supports Python 3.10 and newer.
[2] source=streaming.md | chunk_id=streaming::0
    Shipit agents stream events in real time.
```

The `[N]` indices are stable for the lifetime of the `RAGContext` and
match the citation markers the source tracker attaches to
`AgentResult.rag_sources` when run through an agent.

### Tunable knobs

```python
rag.search(
    "python version",
    top_k=5,
    hybrid_alpha=0.7,        # 1.0=pure vector, 0.0=pure BM25, 0.5=balanced
    enable_reranking=True,   # off by default — adds latency
    enable_recency_bias=True,
    chunks_above=1,
    chunks_below=1,
)
```

### Filters

```python
from shipit_agent.rag import IndexFilters

ctx = rag.search(
    "python",
    top_k=3,
    filters=IndexFilters(
        sources=["readme.md", "install.md"],
        metadata_match={"tags": "install"},
    ),
)
```

`IndexFilters` supports `document_ids`, `sources`, `metadata_match`,
`time_min`, `time_max`. Filters are applied in both branches of the
hybrid pipeline.

### Fetching a specific chunk

```python
chunk = rag.fetch_chunk("readme::0", chunks_above=1, chunks_below=1)
print(chunk.text)
```

---

## Reranking

```python
from shipit_agent.rag import LLMReranker

rag = RAG.default(
    embedder=my_embedder,
    reranker=LLMReranker(llm=my_llm),
)
ctx = rag.search("query", top_k=5, enable_reranking=True)
```

`LLMReranker` is the zero-setup default — it prompts the LLM to score the
top candidates 0–10. For higher-throughput production set-ups swap in a
Cohere reranker or a `sentence-transformers` cross-encoder by
implementing the simple `Reranker` protocol.

---

## Source tracking (without an agent)

Even without an `Agent` you can use the source-tracking helpers directly
to build citation panels for your own UI:

```python
rag.begin_run()
rag.search("python version", top_k=2)
rag.search("streaming events", top_k=1)
sources = rag.end_run()

for s in sources:
    print(f"[{s.index}] {s.source} (chunk {s.chunk_id}, score {s.score:.2f})")
    print(f"    {s.text}")
```

`begin_run` / `end_run` use thread-local state, so concurrent runs on the
same `RAG` do not bleed citations into each other.

---

## See also

- [RAG + Agent](with-agent.md) — auto-wired tools and `result.rag_sources`
- [RAG + Deep Agents](with-deep-agents.md) — every deep-agent pattern
- [API reference](api.md) — every public class and method
- Notebook: `notebooks/22_rag_basics.ipynb`
