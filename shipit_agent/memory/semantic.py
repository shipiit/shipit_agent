from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(slots=True)
class SearchResult:
    """A single search result from semantic memory."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    """Protocol for vector stores."""

    def add(
        self, texts: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> list[str]: ...
    def search(
        self, query_embedding: list[float], top_k: int = 5
    ) -> list[SearchResult]: ...
    def delete(self, ids: list[str]) -> None: ...


class InMemoryVectorStore:
    """Simple in-memory vector store using cosine similarity.

    No external dependencies — uses pure Python math.
    Suitable for development, testing, and small-scale use.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def add(
        self, texts: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> list[str]:
        ids = []
        for i, text in enumerate(texts):
            entry_id = f"mem_{len(self._entries)}"
            self._entries.append(
                {
                    "id": entry_id,
                    "text": text,
                    "embedding": None,  # set by SemanticMemory
                    "metadata": (
                        metadatas[i] if metadatas and i < len(metadatas) else {}
                    ),
                }
            )
            ids.append(entry_id)
        return ids

    def add_with_embeddings(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        ids = []
        for i, text in enumerate(texts):
            entry_id = f"mem_{len(self._entries)}"
            self._entries.append(
                {
                    "id": entry_id,
                    "text": text,
                    "embedding": embeddings[i],
                    "metadata": (
                        metadatas[i] if metadatas and i < len(metadatas) else {}
                    ),
                }
            )
            ids.append(entry_id)
        return ids

    def search(
        self, query_embedding: list[float], top_k: int = 5
    ) -> list[SearchResult]:
        scored = []
        for entry in self._entries:
            emb = entry.get("embedding")
            if emb is None:
                continue
            score = self._cosine_similarity(query_embedding, emb)
            scored.append(
                SearchResult(
                    text=entry["text"],
                    score=score,
                    metadata=entry.get("metadata", {}),
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def delete(self, ids: list[str]) -> None:
        self._entries = [e for e in self._entries if e["id"] not in ids]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class SemanticMemory:
    """Embedding-based memory for semantic search.

    Example::

        def embed(text: str) -> list[float]:
            # your embedding function
            return [0.1, 0.2, ...]

        memory = SemanticMemory(
            vector_store=InMemoryVectorStore(),
            embedding_fn=embed,
        )
        memory.add("Python is a programming language")
        results = memory.search("what programming languages exist?")
    """

    def __init__(
        self,
        *,
        vector_store: InMemoryVectorStore | Any | None = None,
        embedding_fn: Callable[[str], list[float]] | None = None,
        top_k: int = 5,
    ) -> None:
        self.vector_store = vector_store or InMemoryVectorStore()
        self.embedding_fn = embedding_fn
        self.top_k = top_k

    def add(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """Add a fact to semantic memory."""
        if self.embedding_fn:
            embedding = self.embedding_fn(text)
            ids = self.vector_store.add_with_embeddings(
                [text], [embedding], [metadata or {}]
            )
        else:
            ids = self.vector_store.add([text], [metadata or {}])
        return ids[0]

    def add_many(
        self, texts: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> list[str]:
        """Add multiple facts."""
        if self.embedding_fn:
            embeddings = [self.embedding_fn(t) for t in texts]
            return self.vector_store.add_with_embeddings(texts, embeddings, metadatas)
        return self.vector_store.add(texts, metadatas)

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Search for semantically similar facts."""
        if not self.embedding_fn:
            return []
        query_embedding = self.embedding_fn(query)
        return self.vector_store.search(query_embedding, top_k=top_k or self.top_k)
