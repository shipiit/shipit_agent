# RAG API Reference

Complete public surface of `shipit_agent.rag`. Every class is importable
either from `shipit_agent.rag` or from the top-level `shipit_agent`
package (with the `RAG` prefix where there is a name collision with
`shipit_agent.memory`).

---

## Top-level imports

```python
from shipit_agent.rag import (
    RAG,
    # Types
    Document, Chunk, IndexFilters, RAGContext, RAGSource,
    SearchQuery, SearchResult,
    # Components
    DocumentChunker, HashingEmbedder, CallableEmbedder, Embedder,
    InMemoryVectorStore, VectorStore,
    InMemoryBM25Store, KeywordStore,
    LLMReranker, Reranker,
    HybridSearchPipeline,
    # Tools
    RAGSearchTool, RAGFetchChunkTool, RAGListSourcesTool,
    # Utilities
    TextExtractor, RAGDependencyError, RAGIngestError,
)

# Or from the top-level package — the RAG namespace is prefixed to avoid
# colliding with shipit_agent.memory's VectorStore / SearchResult names:
from shipit_agent import (
    RAG,
    RAGChunk, RAGContext, RAGDocument, RAGIndexFilters,
    RAGSearchQuery, RAGSearchResult, RAGSource,
    DocumentChunker, HashingEmbedder, CallableEmbedder,
    HybridSearchPipeline, LLMReranker,
)
```

---

## Dataclasses

### `Document`

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `content` | `str` | required |
| `metadata` | `dict[str, Any]` | `{}` |
| `source` | `str \| None` | `None` |
| `title` | `str \| None` | `None` |
| `created_at` | `datetime \| None` | `None` |

### `Chunk`

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `document_id` | `str` | required |
| `chunk_index` | `int` | required |
| `text` | `str` | required |
| `text_for_embedding` | `str` | defaults to `text` |
| `metadata` | `dict[str, Any]` | `{}` |
| `source` | `str \| None` | `None` |
| `start_char` | `int` | `0` |
| `end_char` | `int` | `0` |
| `embedding` | `list[float] \| None` | `None` |
| `title_embedding` | `list[float] \| None` | `None` |
| `created_at` | `datetime \| None` | `None` |

### `IndexFilters`

| Field | Type | Default |
| --- | --- | --- |
| `document_ids` | `list[str] \| None` | `None` |
| `sources` | `list[str] \| None` | `None` |
| `metadata_match` | `dict[str, Any] \| None` | `None` |
| `time_min` | `datetime \| None` | `None` |
| `time_max` | `datetime \| None` | `None` |

Method:

- `matches(chunk: Chunk) -> bool` — return `True` iff the chunk passes
  every configured filter.

### `SearchQuery`

| Field | Type | Default |
| --- | --- | --- |
| `query` | `str` | required |
| `top_k` | `int` | `10` |
| `filters` | `IndexFilters \| None` | `None` |
| `hybrid_alpha` | `float` | `0.5` |
| `enable_reranking` | `bool` | `False` |
| `enable_recency_bias` | `bool` | `False` |
| `recency_half_life_days` | `float` | `30.0` |
| `chunks_above` | `int` | `0` |
| `chunks_below` | `int` | `0` |

### `SearchResult`

| Field | Type | Default |
| --- | --- | --- |
| `chunk` | `Chunk` | required |
| `score` | `float` | required |
| `vector_score` | `float \| None` | `None` |
| `keyword_score` | `float \| None` | `None` |
| `rerank_score` | `float \| None` | `None` |
| `expanded_above` | `list[Chunk]` | `[]` |
| `expanded_below` | `list[Chunk]` | `[]` |

### `RAGContext`

| Field | Type | Default |
| --- | --- | --- |
| `query` | `str` | required |
| `results` | `list[SearchResult]` | `[]` |
| `total_found` | `int` | `0` |
| `timing_ms` | `dict[str, float]` | `{}` — keys: `embed_ms`, `vector_ms`, `keyword_ms`, `rerank_ms`, `total_ms` |

Methods:

- `to_prompt_context(max_chars: int = 8000) -> str` — render as a
  prompt-ready block with `[N]` citation markers.
- `to_dict() -> dict` — JSON-friendly representation.

### `RAGSource`

| Field | Type | Default |
| --- | --- | --- |
| `index` | `int` | required |
| `chunk_id` | `str` | required |
| `document_id` | `str` | required |
| `text` | `str` | required |
| `score` | `float` | required |
| `source` | `str \| None` | `None` |
| `metadata` | `dict[str, Any]` | `{}` |

Method:

- `to_dict() -> dict` — JSON-friendly representation.

---

## `RAG` facade

```python
class RAG:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedder: Any,
        keyword_store: KeywordStore | None = None,
        reranker: Reranker | None = None,
        chunker: DocumentChunker | None = None,
        auto_embed_on_add: bool = True,
    ) -> None: ...
```

### Class methods

- `RAG.default(*, embedder, reranker=None) -> RAG` — in-memory hybrid
  index with sensible defaults. Recommended starting point.

### Indexing

- `index_text(text, *, document_id=None, title=None, source=None, metadata=None) -> list[Chunk]`
- `index_file(path, *, document_id=None, title=None, metadata=None) -> list[Chunk]`
- `index_document(document: Document) -> list[Chunk]`
- `index_documents(documents: Iterable[Document]) -> list[Chunk]`
- `reindex(document_id, *, content=None) -> list[Chunk]`
- `delete_document(document_id) -> None`

### Query

- `search(query, *, top_k=5, filters=None, hybrid_alpha=0.5, enable_reranking=False, enable_recency_bias=False, chunks_above=0, chunks_below=0) -> RAGContext`
- `fetch_chunk(chunk_id, *, chunks_above=0, chunks_below=0) -> Chunk | None`
- `list_sources() -> list[str]`
- `count() -> int`

### Source tracking

- `begin_run() -> None` — open a per-thread tracker scope.
- `end_run() -> list[RAGSource]` — close the scope and return collected
  sources, indexed `[1..n]` in first-seen order.
- `current_sources() -> list[RAGSource]` — peek at sources captured so
  far inside the active scope.

### Agent integration helpers

- `as_tools() -> list[Tool]` — return the three RAG tools bound to this
  instance.
- `prompt_section() -> str` — return the system-prompt addition that
  describes the RAG tools and citation rules. Override to customise.

---

## Components

### `DocumentChunker`

```python
DocumentChunker(target_tokens=512, overlap_tokens=64, title_prefix_chars=64)
```

Methods:

- `chunk(document: Document) -> list[Chunk]`
- `chunk_many(documents: Iterable[Document]) -> list[Chunk]`

### `HashingEmbedder`

```python
HashingEmbedder(dimension=384, seed="shipit-rag")
```

Stdlib-only, deterministic, L2-normalised. Method:
`embed(texts, *, kind="passage") -> list[list[float]]`.

### `CallableEmbedder`

```python
CallableEmbedder(fn=callable, dimension=int)
```

Wraps any function with the signature
`(list[str]) -> list[list[float]]`. Validates dimensions and length on
every call.

### `InMemoryVectorStore`

Pure-Python `VectorStore` backed by a dict, with `cosine_similarity`
search. Methods follow the `VectorStore` protocol plus `all_chunks()`
for inspecting the full corpus.

### `InMemoryBM25Store`

Pure-Python `KeywordStore` implementing BM25 with `k1=1.5`, `b=0.75`
defaults. Configurable via the constructor.

### `LLMReranker`

```python
LLMReranker(llm, batch_size=10)
```

Reuses any LLM with a `complete(messages=...)` method to score
candidates 0–10. Scores are normalised to `[0, 1]`.

### `HybridSearchPipeline`

```python
HybridSearchPipeline(
    vector_store: VectorStore,
    embedder: Embedder,
    keyword_store: KeywordStore | None = None,
    reranker: Reranker | None = None,
)
```

Method: `search(query: SearchQuery) -> RAGContext`.

Pipeline order: embed → vector + keyword (parallel) → RRF fusion →
optional recency bias → optional reranking → context expansion.

---

## Agent tools

### `RAGSearchTool`

`name="rag_search"`. Parameters:

| Parameter | Type | Default |
| --- | --- | --- |
| `query` | `string` | (required) |
| `top_k` | `integer` | `5` |
| `enable_reranking` | `boolean` | `false` |

Returns a JSON payload with `query`, `total_found`, and a `results`
list containing `citation`, `chunk_id`, `document_id`, `source`,
`score`, and `text` for each hit. The tool's `metadata["rag_chunk_ids"]`
field exposes the captured chunk ids for downstream consumers.

### `RAGFetchChunkTool`

`name="rag_fetch_chunk"`. Parameters:

| Parameter | Type | Default |
| --- | --- | --- |
| `chunk_id` | `string` | (required) |
| `chunks_above` | `integer` | `0` |
| `chunks_below` | `integer` | `0` |

Returns a JSON payload with the chunk text plus optional
`context_above` / `context_below` arrays of neighbouring chunks.

### `RAGListSourcesTool`

`name="rag_list_sources"`. No parameters. Returns
`{"sources": ["readme.md", "manual.pdf", ...]}`.

---

## Errors

- `RAGDependencyError(RuntimeError)` — raised when an optional dependency
  required by an extractor or adapter is missing.
- `RAGIngestError(RuntimeError)` — raised by `TextExtractor.extract`
  when a file cannot be read or parsed. Carries `path` and `cause`
  attributes.

---

## See also

- [Overview](index.md)
- [Standalone RAG](standalone.md)
- [RAG + Agent](with-agent.md)
- [RAG + Deep Agents](with-deep-agents.md)
- [Adapters](adapters.md)
