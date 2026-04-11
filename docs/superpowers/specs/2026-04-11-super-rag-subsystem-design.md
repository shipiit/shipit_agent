# Super RAG Subsystem — Design Spec

**Date:** 2026-04-11
**Status:** Draft — awaiting review
**Owner:** shipit_agent
**Target module:** `shipit_agent/rag/`

---

## 1. Goal

Add a **Super RAG subsystem** to shipit_agent that is:

1. **Powerful** — matches the retrieval quality of the Onyx-style stack used in DRK_CACHE:
   hybrid search (vector + keyword with RRF fusion), optional reranking, title+metadata
   suffix chunking, context expansion (chunks above/below), recency bias.
2. **Easy** — `Agent(llm=..., rag=my_rag)` auto-wires RAG tools; a user can index a file
   in one line and query it from any agent.
3. **Pluggable** — protocol-driven `VectorStore`, `Embedder`, `Reranker`, `KeywordStore`,
   so production users can swap in Chroma, Qdrant, pgvector, or an existing DRK_CACHE
   database.
4. **Zero required deps** — defaults work with only `numpy` (already a shipit_agent dep).
   Heavy backends (`chromadb`, `qdrant-client`, `psycopg2`, `rank_bm25`) are lazy imports.
5. **Backward-compatible** — ships as a new package; no breaking changes to existing
   `Agent`, `GoalAgent`, `Supervisor`, or other deep agents. The `rag=` parameter is
   additive.

## 2. Non-Goals

- **No new deep-agent pattern.** We are NOT adding LangChain-style `write_todos`, virtual
  filesystem, or sub-agent-as-tool primitives. That is a separate spec if desired.
- **No Django/ORM layer.** The DRK_CACHE adapter is a `psycopg2` client
  (read-only by default, opt-in write support), not a Django integration.
- **No training/fine-tuning of embeddings.** We consume existing embedding providers.
- **No evaluation harness in v1.** A benchmarking CLI (`rag-eval`) is out of scope.

## 3. User-Facing API

### 3.1 Quickstart

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG
from anthropic import Anthropic

llm = Anthropic()
rag = RAG.default(embedder=llm)          # InMemory vector + BM25 keyword
rag.index_file("docs/manual.pdf")
rag.index_text("Shipit supports Python 3.10+.", metadata={"source": "readme"})

agent = Agent.with_builtins(llm=llm, rag=rag)
result = agent.run("What Python version does Shipit support?")
print(result.output)
# The agent calls rag_search("Python version") under the hood and cites chunks.
```

### 3.2 Direct retrieval (no agent)

```python
context = rag.search("installation steps", top_k=5, enable_reranking=True)
print(context.to_prompt_context(max_chars=4000))
for r in context.results:
    print(f"[{r.score:.2f}] {r.chunk.metadata.get('source')}: {r.chunk.text[:100]}")
```

### 3.2.1 Agent answers with sources (DRK_CACHE-style)

Every RAG-equipped agent run returns both the answer and the chunks that backed it.
The `AgentResult` gains a `rag_sources` field when a RAG is attached:

```python
agent = Agent.with_builtins(llm=llm, rag=rag)
result = agent.run("What Python version does Shipit support?")

print(result.output)
# "Shipit supports Python 3.10+. [1]"

for src in result.rag_sources:
    print(f"[{src.index}] {src.source} (chunk {src.chunk_id}, score {src.score:.2f})")
    print(f"    {src.text[:120]}")
# [1] readme (chunk readme::0, score 0.87)
#     Shipit supports Python 3.10+.
```

The same applies to every deep agent (`GoalAgent`, `ReflectiveAgent`, `AdaptiveAgent`,
`Supervisor`, `PersistentAgent`) — they all expose `result.rag_sources` when run with
`rag=...`. Streaming agents emit a `rag_sources` event as each tool call completes,
and a final `rag_sources_consolidated` event at the end with the full list.

### 3.3 Fetching a specific chunk

```python
chunk = rag.fetch_chunk("manual.pdf::12")
print(chunk.text)

# With context expansion
chunk_with_context = rag.fetch_chunk("manual.pdf::12", chunks_above=1, chunks_below=1)
```

### 3.4 Connecting an existing DRK_CACHE database

```python
from shipit_agent.rag.adapters import DrkCacheVectorStore

store = DrkCacheVectorStore(
    dsn="postgresql://user:pass@host:5432/drk_cache",
    knowledge_base_ids=[1, 2, 3],     # scope to specific KBs
)
rag = RAG(vector_store=store, embedder=my_embedder)  # read-only
agent = Agent.with_builtins(llm=llm, rag=rag)
agent.run("Summarize what we know about customer X.")
```

### 3.5 Using with a deep agent

```python
from shipit_agent.deep import GoalAgent, Goal

goal_agent = GoalAgent.with_builtins(
    llm=llm,
    goal=Goal(
        objective="Write a 1-page summary of our onboarding process",
        success_criteria=["Covers signup", "Covers first-run UX", "Covers support flow"],
    ),
    rag=rag,                           # same parameter as Agent
)
for event in goal_agent.stream():
    print(event.message)
```

### 3.6 Plugging in alternative backends

```python
from shipit_agent.rag.adapters import ChromaVectorStore, QdrantVectorStore, PgVectorStore

rag = RAG(vector_store=ChromaVectorStore(path="./chroma_db"), embedder=llm)
rag = RAG(vector_store=QdrantVectorStore(url="http://localhost:6333"), embedder=llm)
rag = RAG(vector_store=PgVectorStore(dsn="...", table="my_chunks"), embedder=llm)
```

## 4. Architecture

```
shipit_agent/rag/
├── __init__.py              # Public exports: RAG, Chunk, Document, SearchQuery, ...
├── types.py                 # Dataclasses: Document, Chunk, SearchQuery, SearchResult,
│                            #              IndexFilters, RAGContext
├── chunker.py               # DocumentChunker (sentence-aware, title prefix,
│                            #                   metadata suffix — Onyx-style)
├── embedder.py              # Embedder protocol + AnthropicEmbedder, OpenAIEmbedder,
│                            #                      SentenceTransformerEmbedder,
│                            #                      CallableEmbedder
├── vector_store.py          # VectorStore protocol + InMemoryVectorStore (numpy cosine)
├── keyword_store.py         # KeywordStore protocol + InMemoryBM25Store
│                            #                          (rank_bm25, lazy import)
├── search_pipeline.py       # HybridSearchPipeline: vector + keyword + RRF + rerank +
│                            #                      context expansion + recency bias
├── reranker.py              # Reranker protocol + LLMReranker (uses agent's own LLM)
│                            #                    + CohereReranker (lazy)
├── rag.py                   # RAG facade — the main class users touch
├── extractors.py            # TextExtractor — PDF/DOCX/TXT/MD/HTML/CSV/JSON
│                            #                 (all lazy imports)
├── tools.py                 # rag_search_tool, rag_fetch_chunk_tool,
│                            #                  rag_list_sources_tool
└── adapters/
    ├── __init__.py
    ├── drk_cache.py         # DrkCacheVectorStore
    ├── chroma.py            # ChromaVectorStore
    ├── qdrant.py            # QdrantVectorStore
    └── pgvector.py          # PgVectorStore
```

### 4.1 Module dependency graph

```
rag.py  ──►  search_pipeline.py  ──►  vector_store.py
                                 ──►  keyword_store.py
                                 ──►  reranker.py
      ──►  chunker.py  ──►  types.py
      ──►  embedder.py
      ──►  extractors.py
      ──►  tools.py  ──►  (shipit_agent.tools Tool protocol)

adapters/*  ──►  vector_store.py  (implement VectorStore protocol)
```

### 4.2 Agent integration

- `Agent.__init__` gains an optional `rag: RAG | None = None` parameter.
- When `rag` is set, the Agent auto-appends three tools to its `tools` list:
  `rag_search_tool(rag)`, `rag_fetch_chunk_tool(rag)`, `rag_list_sources_tool(rag)`.
- The system prompt is augmented with a short RAG section: *"You have access to a RAG
  knowledge base. When the user asks about facts, documents, or past conversations,
  call `rag_search` first. In your final answer, cite sources using [N] markers that
  correspond to chunks you used. Never invent a citation."*
- `Agent.with_builtins` passes `rag` through.
- `GoalAgent`, `ReflectiveAgent`, `AdaptiveAgent`, `Supervisor`, `PersistentAgent` all
  forward `rag` to the inner `Agent` they build.

### 4.3 Source tracking (DRK_CACHE parity)

Every chunk the agent retrieves during a run is recorded in a per-run
`SourceTracker` maintained by the `AgentRuntime`. The tracker:

1. Wraps the three `rag_*` tools with a post-run hook that captures every chunk
   returned by `rag_search` and every chunk fetched by `rag_fetch_chunk`.
2. De-duplicates by `chunk_id`, assigns a stable citation index (`[1]`, `[2]`, ...)
   in the order chunks were first seen.
3. At `run_completed`, attaches `rag_sources: list[RAGSource]` to the `AgentResult`.
4. During `stream()`, emits two new `AgentEvent` types:
   - `rag_sources` — per-tool-call, payload = chunks just added
   - `rag_sources_consolidated` — emitted once at the end, payload = full list

This means any surface that renders an agent run (CLI, `shipit_ui`, custom
integrations) gets free DRK_CACHE-style source panels without extra wiring — the
sources travel with the result.

## 5. Core Types

```python
@dataclass
class Document:
    id: str                            # user-provided or auto (uuid)
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None          # file path, URL, or free-form source label
    created_at: datetime | None = None

@dataclass
class Chunk:
    id: str                            # "{document_id}::{chunk_index}"
    document_id: str
    chunk_index: int
    text: str                          # raw chunk text (for display)
    text_for_embedding: str            # title_prefix + text + metadata_suffix
    metadata: dict[str, Any]
    start_char: int = 0
    end_char: int = 0
    embedding: list[float] | None = None
    title_embedding: list[float] | None = None

@dataclass
class IndexFilters:
    document_ids: list[str] | None = None
    sources: list[str] | None = None
    metadata_match: dict[str, Any] | None = None
    time_min: datetime | None = None
    time_max: datetime | None = None

@dataclass
class SearchQuery:
    query: str
    top_k: int = 10
    filters: IndexFilters | None = None
    hybrid_alpha: float = 0.5          # 1.0=pure vector, 0.0=pure keyword
    enable_reranking: bool = False
    enable_recency_bias: bool = False
    chunks_above: int = 0
    chunks_below: int = 0

@dataclass
class SearchResult:
    chunk: Chunk
    score: float                       # final fused score [0..1]
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    expanded_above: list[Chunk] = field(default_factory=list)
    expanded_below: list[Chunk] = field(default_factory=list)

@dataclass
class RAGContext:
    query: str
    results: list[SearchResult]
    total_found: int
    timing_ms: dict[str, float]        # {"embed":12,"vector":8,"keyword":3,
                                       #  "rerank":45,"total":68}

    def to_prompt_context(self, max_chars: int = 8000) -> str:
        """Format as a prompt-ready context block with [N] citation markers.

        Each chunk is rendered as:
            [1] source=readme | chunk_id=readme::0
                Shipit supports Python 3.10+.

        The [N] indices are stable for the lifetime of this RAGContext and
        match the citation indices the SourceTracker will later attach to
        the AgentResult.
        """

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class RAGSource:
    """A source citation attached to an AgentResult after a RAG-backed run."""
    index: int                         # citation number ([1], [2], ...)
    chunk_id: str
    document_id: str
    source: str | None                 # file path, URL, or label
    text: str                          # chunk text (for preview/rendering)
    score: float                       # final fused score
    metadata: dict[str, Any]           # passthrough (title, tags, kb_id, etc.)
```

`AgentResult` (existing dataclass in `shipit_agent/models.py`) gains one optional
field:

```python
@dataclass
class AgentResult:
    # ...existing fields...
    rag_sources: list[RAGSource] = field(default_factory=list)
```


## 6. Key Components

### 6.1 `DocumentChunker` (chunker.py)

**Onyx-style chunking.** Produces `Chunk` instances with:

- **title_prefix**: First 64 chars of document title prepended to every chunk's
  `text_for_embedding`.
- **metadata_suffix_semantic**: `"Source: {source} | Tags: {tags}"` appended.
- **Sentence boundaries**: splits on sentence ends first, only breaking mid-sentence
  when a single sentence exceeds the chunk budget.
- **Token budget**: approximated via `len(text) / 4` (same heuristic as existing
  shipit_agent `context_tracker.py`).
- **Chunk size defaults**: target 512 tokens, overlap 64 tokens. Configurable.

**API:**
```python
chunker = DocumentChunker(target_tokens=512, overlap_tokens=64)
chunks: list[Chunk] = chunker.chunk(document)   # where document: Document
```

### 6.2 `Embedder` (embedder.py)

**Protocol:**
```python
class Embedder(Protocol):
    dimension: int                                  # e.g. 1536, 1024, 384
    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]: ...
    async def aembed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]: ...
```

**Built-in implementations:**
- `AnthropicEmbedder` — wraps the Anthropic client's embed endpoint if available;
  else falls back to `CallableEmbedder` over a user-supplied function.
- `OpenAIEmbedder` — wraps `text-embedding-3-small` / `-large` (lazy `openai` import).
- `SentenceTransformerEmbedder` — local embeddings via `sentence-transformers`
  (lazy, for offline/dev use).
- `CallableEmbedder(fn, dimension)` — for user-provided functions.
- `HashingEmbedder(dimension=384)` — deterministic feature-hashing fallback used in
  tests and when no embedder is configured. Lets the library run with zero deps.

**LLM-as-embedder shim:** `RAG.default(embedder=llm)` accepts any LLM that exposes an
`embed()` method; otherwise it wraps the LLM in `HashingEmbedder` and logs a warning.

### 6.3 `VectorStore` (vector_store.py)

**Protocol:**
```python
class VectorStore(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def delete(self, chunk_ids: list[str]) -> None: ...
    def delete_document(self, document_id: str) -> None: ...
    def get(self, chunk_id: str) -> Chunk | None: ...
    def get_many(self, chunk_ids: list[str]) -> list[Chunk]: ...
    def list_chunks(self, document_id: str) -> list[Chunk]: ...
    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: IndexFilters | None = None,
    ) -> list[tuple[Chunk, float]]: ...
    def count(self) -> int: ...
    def list_sources(self) -> list[str]: ...
```

**`InMemoryVectorStore`** — stores chunks in a dict, embeddings in a numpy matrix.
Cosine similarity via a single `numpy` dot product. Supports filtering via a
post-filter pass (fast enough for <100k chunks, which is the in-memory target).

### 6.4 `KeywordStore` (keyword_store.py)

**Protocol:** Same shape as `VectorStore.search`, but the query is a plain string and
the backing impl uses BM25 (via `rank_bm25` — lazy import). A pure-Python fallback
tokenizer is provided; if `rank_bm25` is missing, the keyword branch is skipped and
the pipeline runs vector-only (warning logged once).

### 6.5 `HybridSearchPipeline` (search_pipeline.py)

**Executes, in order:**

1. **Embed query** (with `kind="query"`).
2. **Vector search**: top `k*2` from `VectorStore.search`.
3. **Keyword search**: top `k*2` from `KeywordStore.search` (parallel with vector via
   `concurrent.futures.ThreadPoolExecutor` when both are available).
4. **RRF fusion**: `score = sum(1 / (60 + rank_i))` across vector/keyword lists,
   weighted by `hybrid_alpha`.
5. **Optional recency bias**: exponential decay `score *= exp(-age_days / half_life)`
   (half_life=30d default, configurable).
6. **Optional reranking**: pass top `k*2` through `Reranker.rerank(query, chunks)`
   and resort.
7. **Context expansion**: for each top-k chunk, fetch `chunks_above` and
   `chunks_below` from the same document via `VectorStore.list_chunks`.
8. Return `RAGContext`.

### 6.6 `Reranker` (reranker.py)

**Protocol:**
```python
class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[tuple[Chunk, float]]: ...
```

**Implementations:**
- `LLMReranker(llm, batch_size=10)` — default. Prompts the LLM to score each chunk
  0..10 for relevance. Uses the same LLM as the agent (no extra dep).
- `CohereReranker` — lazy, calls `cohere.rerank`.
- `CrossEncoderReranker` — lazy, `sentence-transformers` cross-encoder.

### 6.7 `RAG` facade (rag.py)

**Public API:**
```python
class RAG:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedder: Embedder | Any,            # Any for LLM-with-embed duck typing
        keyword_store: KeywordStore | None = None,
        reranker: Reranker | None = None,
        chunker: DocumentChunker | None = None,
    ): ...

    @classmethod
    def default(cls, *, embedder: Any) -> "RAG":
        """InMemory vector + keyword + default chunker."""

    # --- indexing ---
    def index_text(self, text: str, *, document_id: str | None = None,
                   metadata: dict | None = None, source: str | None = None) -> list[Chunk]: ...
    def index_file(self, path: str, *, metadata: dict | None = None) -> list[Chunk]: ...
    def index_document(self, document: Document) -> list[Chunk]: ...
    def index_documents(self, documents: list[Document]) -> list[Chunk]: ...
    def reindex(self, document_id: str) -> list[Chunk]: ...
    def delete_document(self, document_id: str) -> None: ...

    # --- query ---
    def search(self, query: str, **kwargs) -> RAGContext:
        """kwargs: top_k, filters, hybrid_alpha, enable_reranking, enable_recency_bias,
                   chunks_above, chunks_below"""
    def fetch_chunk(self, chunk_id: str, *, chunks_above: int = 0,
                    chunks_below: int = 0) -> Chunk | None: ...
    def list_sources(self) -> list[str]: ...
    def count(self) -> int: ...

    # --- agent helpers ---
    def as_tools(self) -> list[Tool]:
        """Return the 3 RAG tools the Agent wires automatically."""
```

### 6.8 Agent tools (tools.py)

Three tools, following shipit_agent's existing `Tool` protocol:

**`rag_search`**
```json
{
  "name": "rag_search",
  "description": "Search the knowledge base for relevant chunks. Use when the user asks about facts, documents, code, or past conversations that may be stored.",
  "parameters": {
    "query": "string — natural language search query",
    "top_k": "integer — default 5",
    "enable_reranking": "boolean — default false (enable for quality at latency cost)"
  },
  "returns": "List of {chunk_id, text, source, score}"
}
```

**`rag_fetch_chunk`**
```json
{
  "name": "rag_fetch_chunk",
  "description": "Fetch the full text of a specific chunk by its ID, optionally with surrounding context.",
  "parameters": {
    "chunk_id": "string",
    "chunks_above": "integer — default 0",
    "chunks_below": "integer — default 0"
  },
  "returns": "{chunk_id, text, metadata, expanded_context}"
}
```

**`rag_list_sources`**
```json
{
  "name": "rag_list_sources",
  "description": "List the distinct sources in the knowledge base.",
  "parameters": {},
  "returns": "List of source labels"
}
```

### 6.9 `DrkCacheVectorStore` adapter (adapters/drk_cache.py)

**Behavior:**
- Connects via `psycopg2` (lazy import).
- **Read-only by default** — raises on `add/delete` unless `writable=True`.
- Implements `search` by running the same pgvector query used in
  `drk_cache/chats/Service/rag/search_pipeline.py`:
  ```sql
  SELECT id, document_id, knowledge_base_id, chunk_text, chunk_index, metadata,
         1 - (embedding <=> %s::vector) as similarity
  FROM drkcache_kb_chunk
  WHERE knowledge_base_id = ANY(%s) AND embedding IS NOT NULL
  ORDER BY similarity DESC LIMIT %s;
  ```
- Maps `drkcache_kb_chunk` rows to `Chunk` dataclasses — `chunk.id` is
  `f"{document_id}::{chunk_index}"`, original numeric ID preserved in
  `chunk.metadata["drk_chunk_id"]`.
- Constructor args:
  ```python
  DrkCacheVectorStore(
      dsn: str,
      knowledge_base_ids: list[int] | None = None,
      embedding_dimension: int = 1024,
      writable: bool = False,
  )
  ```
- **Embedding dimension constraint**: the user's `Embedder.dimension` must equal
  `embedding_dimension` (default 1024 to match the DRK_CACHE schema). Mismatch raises
  at `RAG.__init__`.

## 7. Data Flow

### 7.1 Indexing flow

```
user calls rag.index_file("doc.pdf")
    │
    ▼
TextExtractor.extract(path)  →  raw text
    │
    ▼
Document(id, content, source, metadata)
    │
    ▼
DocumentChunker.chunk(doc)   →  list[Chunk] (no embeddings yet)
    │
    ▼
Embedder.embed([c.text_for_embedding for c in chunks], kind="passage")
    │
    ▼
chunks with .embedding set
    │
    ▼
VectorStore.add(chunks)       &&   KeywordStore.add(chunks)   [parallel]
```

### 7.2 Query flow (from the agent)

```
agent LLM decides to call rag_search(query="...")
    │
    ▼
rag.search(query)
    │
    ▼
Embedder.embed([query], kind="query")   →  query_vector
    │
    ├─► VectorStore.search(query_vector, k*2)   ──┐
    │                                              ├─ ThreadPoolExecutor
    └─► KeywordStore.search(query, k*2)         ──┘
                                                   │
                                                   ▼
                                               RRF fusion
                                                   │
                                                   ▼
                                            [optional] recency bias
                                                   │
                                                   ▼
                                            [optional] reranker
                                                   │
                                                   ▼
                                            context expansion
                                                   │
                                                   ▼
                                               RAGContext
    │
    ▼
RAGContext.to_prompt_context()   →  returned to LLM as tool result
```

## 8. Error Handling

- **Missing optional deps**: lazy imports raise `RAGDependencyError` with a clear
  install hint — e.g. *"ChromaVectorStore requires `pip install chromadb`"*.
- **Embedder dimension mismatch** with vector store: raised at `RAG.__init__` with
  both dimensions reported.
- **Empty index**: `RAG.search` on an empty store returns `RAGContext(results=[], ...)`
  — no exception.
- **Chunk not found** in `fetch_chunk`: returns `None` (not an exception) so the LLM
  can recover gracefully.
- **File extraction failure**: `index_file` raises `RAGIngestError(path, cause)`.
- **Search timeout**: `search_pipeline` wraps vector+keyword in a `Future.result(timeout=...)`
  with default 10s; exceeding it returns whatever branch finished and logs a warning.
- **Embedder failure mid-index**: the partial batch is not written; exception bubbles up.
  `index_documents` is not transactional across documents — one failed doc aborts the
  loop, already-indexed docs remain.

## 9. Testing Strategy

All tests live in `tests/rag/` (new subdir). **Written TDD — tests before implementation.**

### 9.1 Unit tests

- `test_types.py` — dataclass equality, `RAGContext.to_prompt_context` formatting and
  `max_chars` truncation.
- `test_chunker.py` — sentence splits, title prefix, metadata suffix, overlap, edge
  cases (empty doc, single-sentence doc, extreme doc).
- `test_embedder.py` — `HashingEmbedder` determinism; dimension consistency; batch
  embedding preserves order; `CallableEmbedder` wraps functions correctly.
- `test_vector_store_in_memory.py` — add, delete, get, list_chunks, search ordering,
  filters (document_ids, sources, metadata_match), count.
- `test_keyword_store_in_memory.py` — BM25 ordering, stopword handling, filter
  parity with vector store.
- `test_search_pipeline.py` — RRF fusion math (known-good vectors), recency bias
  decay, hybrid_alpha extremes (0.0 and 1.0 reduce to pure-keyword/pure-vector),
  context expansion pulls correct neighbors.
- `test_reranker_llm.py` — mock LLM, verify prompt format and score parsing.
- `test_rag_facade.py` — end-to-end `index_text → search → fetch_chunk` roundtrip;
  reindex replaces old chunks; delete_document removes from both stores.
- `test_tools.py` — tool schemas valid; `rag_search` tool returns well-formed JSON;
  tools resilient to empty store.
- `test_agent_integration.py` — `Agent(rag=...)` auto-appends tools; system prompt
  augmented; `Agent.with_builtins(rag=...)` works; `GoalAgent(rag=...)` forwards.
- `test_extractors.py` — mocked PDF/DOCX/TXT/MD extraction (real deps skipped if
  not installed via `pytest.importorskip`).

### 9.2 Adapter tests

- `test_adapter_drk_cache.py` — mocked psycopg2 cursor returning canned rows;
  verify row → Chunk mapping, dimension-mismatch error, `writable=False` guard.
- `test_adapter_chroma.py`, `test_adapter_qdrant.py`, `test_adapter_pgvector.py` —
  `pytest.importorskip` gates; thin smoke tests against in-process/dockerized
  backends in CI (optional job).

### 9.3 Integration tests

- `test_rag_with_goal_agent.py` — GoalAgent with RAG solves a mini research task
  using 3 synthetic docs. Mocked LLM.
- `test_rag_large_corpus.py` — index 1k synthetic docs, measure search latency is
  < 500ms on the in-memory backend. Skipped by default, run via `-m perf`.

### 9.4 Coverage target

- 90%+ line coverage on `shipit_agent/rag/*.py` excluding `adapters/*` (adapters
  gated behind optional deps).

## 10. Implementation Phases

1. **Phase 1 — Foundation (types, chunker, in-memory stores).**
   Files: `types.py`, `chunker.py`, `embedder.py` (with `HashingEmbedder` only),
   `vector_store.py`, `keyword_store.py`. Full unit test coverage. Ships working
   vector-only RAG with zero deps.

2. **Phase 2 — Search pipeline + facade.**
   Files: `search_pipeline.py`, `reranker.py` (LLMReranker only), `rag.py`,
   `extractors.py` (TXT/MD only; PDF/DOCX gated), `__init__.py`. End-to-end
   `rag.index_text → rag.search` works.

3. **Phase 3 — Agent integration.**
   Files: `tools.py`, modifications to `shipit_agent/agent.py`,
   `shipit_agent/deep/goal_agent.py`, `shipit_agent/deep/reflective_agent.py`,
   `shipit_agent/deep/adaptive_agent.py`, `shipit_agent/deep/supervisor.py`,
   `shipit_agent/deep/persistent_agent.py`. All accept `rag=` parameter.

4. **Phase 4 — Real embedders + extractors.**
   `AnthropicEmbedder`, `OpenAIEmbedder`, `SentenceTransformerEmbedder`; PDF/DOCX
   extraction via lazy `pypdf`, `python-docx`.

5. **Phase 5 — Adapters.**
   `DrkCacheVectorStore` first (priority), then `ChromaVectorStore`,
   `QdrantVectorStore`, `PgVectorStore`.

6. **Phase 6 — Docs + examples.**
   README section, `examples/rag_quickstart.py`,
   `examples/rag_drk_cache_adapter.py`,
   `examples/goal_agent_with_rag.py`.

Each phase is a separate PR-sized unit. Phases 1-3 are the minimum viable product;
4-6 are enhancements that can ship in follow-up PRs.

## 11. Public Exports

Top-level `shipit_agent/__init__.py` additions:

```python
from shipit_agent.rag import (
    RAG, Document, Chunk, SearchQuery, SearchResult, IndexFilters, RAGContext,
    DocumentChunker, HybridSearchPipeline, InMemoryVectorStore, InMemoryBM25Store,
    HashingEmbedder, LLMReranker,
)
```

Adapters imported from `shipit_agent.rag.adapters` (not re-exported at top level to
avoid pulling optional deps at import time).

## 12. Backward Compatibility

- Zero breaking changes. The `rag=` parameter defaults to `None`; existing code
  continues to work unchanged.
- No existing tool names clash with `rag_search`, `rag_fetch_chunk`,
  `rag_list_sources` (verified against `shipit_agent/tools/`).
- `shipit_agent.rag` is a new top-level package; no name collisions.

## 13. Open Questions (Resolved)

| # | Question | Decision |
|---|----------|----------|
| 1 | Single combined "deep RAG agent" spec or just RAG subsystem? | RAG subsystem only (user: option C). |
| 2 | Integration API shape? | New `rag=` parameter on Agent / deep agents. |
| 3 | Storage backend philosophy? | Pluggable protocol + InMemory default + lazy adapters. |
| 4 | Support reading existing DRK_CACHE data? | Yes — dedicated `DrkCacheVectorStore` adapter. |
| 5 | Feature tier? | Full Onyx-style: hybrid + RRF + rerank + context expansion. |

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `rank_bm25` not installed → keyword branch silently skipped | Log warning on first search; document in README. Pipeline degrades gracefully to vector-only. |
| Users plug a 384-dim embedder into a 1024-dim DRK_CACHE store | `RAG.__init__` validates `embedder.dimension == vector_store.dimension` and raises. |
| In-memory store grows unbounded | Document 100k-chunk practical ceiling; recommend Chroma/Qdrant/pgvector above that. |
| LLMReranker is slow (adds 10-20x latency) | Off by default; enabled per-query via `enable_reranking=True`. |
| DRK_CACHE schema drift | Adapter targets a specific schema version; constructor accepts `table_name` and `embedding_column` overrides for flexibility. |
| Agent over-calls `rag_search` | System prompt guidance: "Only call `rag_search` when the user's question references facts you don't already know from the conversation." |

## 15. What This Does NOT Do (Explicit Non-Goals Recap)

- Does **not** add LangChain `deepagents`-style planning tool, virtual filesystem, or
  sub-agent-as-tool. That is a separate future spec.
- Does **not** replace or modify any existing deep agent's reasoning loop.
- Does **not** introduce a RAG-specific session or memory store — it reuses
  `SessionStore`/`MemoryStore` as-is.
- Does **not** bundle any embedding or reranker API keys — users configure their own.
- Does **not** provide a web UI — surfacing in `shipit_ui` is a separate effort.
