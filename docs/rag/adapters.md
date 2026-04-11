# RAG Adapters

The defaults that ship with `shipit_agent.rag` are pure-Python and live
entirely in memory. They are perfect for tests, demos, and small
corpora — but for production-grade indexes you usually want a backing
store that persists, scales, or that you already have data in.

The RAG subsystem is built around **plain Python protocols** for the
storage layer:

- `VectorStore` — `add`, `delete`, `get`, `list_chunks`, `search`, `count`
- `KeywordStore` — `add`, `delete`, `search`, `count`
- `Embedder` — `embed(texts, kind=...)` → `list[list[float]]`
- `Reranker` — `rerank(query, chunks, top_k)` → `list[(Chunk, score)]`

Anything implementing those protocols is a valid backend. The
`shipit_agent.rag.adapters` package collects ready-to-use
implementations.

---

## Built-in defaults

| Class | Module | Notes |
| --- | --- | --- |
| `InMemoryVectorStore` | `shipit_agent.rag.vector_store` | Pure-Python cosine over a dict |
| `InMemoryBM25Store` | `shipit_agent.rag.keyword_store` | Pure-Python BM25 with stopword filtering |
| `HashingEmbedder` | `shipit_agent.rag.embedder` | Deterministic feature-hashing — stdlib only, suitable for tests |
| `CallableEmbedder` | `shipit_agent.rag.embedder` | Wraps any `fn(list[str]) -> list[list[float]]` |
| `LLMReranker` | `shipit_agent.rag.reranker` | Reuses your agent's LLM as a relevance judge |

These are good enough for tests, local development, and corpora up to a
few thousand chunks.

---

## DRK_CACHE adapter

Read existing pgvector indexes from a DRK_CACHE backend over `psycopg2`,
without going through Django.

```python
from shipit_agent.rag import RAG
from shipit_agent.rag.adapters.drk_cache import DrkCacheVectorStore

store = DrkCacheVectorStore(
    dsn="postgresql://user:pass@host:5432/drk_cache",
    knowledge_base_ids=[1, 2, 3],
    embedding_dimension=1024,   # must match your embedder
    writable=False,             # read-only by default
)

rag = RAG(vector_store=store, embedder=my_1024_dim_embedder)
agent = Agent(llm=my_llm, rag=rag)
```

> **Embedding dimension constraint** — your `Embedder.dimension` must
> equal `DrkCacheVectorStore.embedding_dimension` (default 1024). The
> `RAG` constructor validates this up front and raises a clear error
> on mismatch, so you don't silently get garbage results.

The adapter maps `drkcache_kb_chunk` rows directly to `Chunk`
dataclasses. The original numeric DRK_CACHE chunk id is preserved in
`chunk.metadata["drk_chunk_id"]`.

---

## Bringing your own embedder

Wrap any function that turns text into vectors:

```python
from shipit_agent.rag import CallableEmbedder
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

def embed(texts):
    return [v.tolist() for v in model.encode(texts)]

embedder = CallableEmbedder(fn=embed, dimension=384)
rag = RAG.default(embedder=embedder)
```

Or, for a tighter integration, implement the protocol directly:

```python
from shipit_agent.rag import Embedder

class OpenAIEmbedder(Embedder):
    dimension = 1536
    def __init__(self, client):
        self.client = client
    def embed(self, texts, *, kind="passage"):
        resp = self.client.embeddings.create(model="text-embedding-3-small", input=texts)
        return [d.embedding for d in resp.data]
```

---

## Bringing your own vector store

Implement the `VectorStore` protocol — every method takes plain
dataclasses, no framework lock-in:

```python
from shipit_agent.rag import VectorStore, Chunk, IndexFilters

class MyChromaStore(VectorStore):
    def __init__(self, collection):
        self.col = collection

    def add(self, chunks):
        self.col.add(
            ids=[c.id for c in chunks],
            embeddings=[c.embedding for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[{**c.metadata, "source": c.source} for c in chunks],
        )

    def delete(self, chunk_ids):
        self.col.delete(ids=chunk_ids)

    def delete_document(self, document_id):
        self.col.delete(where={"document_id": document_id})

    def get(self, chunk_id):
        # Return a Chunk or None
        ...

    def get_many(self, chunk_ids):
        ...

    def list_chunks(self, document_id):
        ...

    def search(self, query_embedding, top_k, filters=None):
        results = self.col.query(query_embeddings=[query_embedding], n_results=top_k)
        return [(self._row_to_chunk(row), score) for row, score in zip(results["ids"][0], results["distances"][0])]

    def count(self):
        return self.col.count()

    def list_sources(self):
        ...
```

The same shape works for Qdrant, Weaviate, Pinecone, Milvus, FAISS,
LanceDB, etc. — any vector backend with a similarity-search method.

---

## Bringing your own reranker

```python
from shipit_agent.rag import Reranker

class CohereReranker(Reranker):
    def __init__(self, client, model="rerank-english-v3.0"):
        self.client = client
        self.model = model

    def rerank(self, query, chunks, top_k):
        resp = self.client.rerank(
            model=self.model,
            query=query,
            documents=[c.text for c in chunks],
            top_n=top_k,
        )
        return [(chunks[r.index], r.relevance_score) for r in resp.results]
```

Plug it into the `RAG` constructor:

```python
rag = RAG.default(embedder=my_embedder, reranker=CohereReranker(client=cohere_client))
```

---

## Picking the right defaults

| Corpus size | Recommended setup |
| --- | --- |
| < 1k chunks (tests, demos) | `RAG.default(embedder=HashingEmbedder())` |
| 1k–100k chunks (single-user app) | `RAG.default(embedder=OpenAIEmbedder())` |
| > 100k chunks, persistent | Custom `VectorStore` over Chroma / Qdrant / pgvector |
| Existing DRK_CACHE deployment | `DrkCacheVectorStore` |
| High-quality retrieval critical | Add `LLMReranker` or `CohereReranker` |

---

## See also

- [Standalone RAG](standalone.md) — full indexing and search reference
- [API reference](api.md) — every protocol and dataclass field
