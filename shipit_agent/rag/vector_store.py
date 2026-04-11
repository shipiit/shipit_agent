"""Vector store protocol and in-memory implementation.

The in-memory store is pure Python — no numpy required — and is suitable
for the common case of a few thousand chunks. Production users should
swap in one of the adapters under :mod:`shipit_agent.rag.adapters` for
larger corpora.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .embedder import cosine_similarity
from .types import Chunk, IndexFilters


@runtime_checkable
class VectorStore(Protocol):
    """Protocol that all vector stores must implement."""

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


@dataclass
class InMemoryVectorStore:
    """Dict-backed vector store with pure-Python cosine search."""

    _chunks: dict[str, Chunk] = field(default_factory=dict)
    _by_document: dict[str, list[str]] = field(default_factory=dict)

    def add(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
            bucket = self._by_document.setdefault(chunk.document_id, [])
            if chunk.id not in bucket:
                bucket.append(chunk.id)
        # Keep per-document chunks sorted by chunk_index so neighbours are predictable.
        for doc_id, ids in self._by_document.items():
            ids.sort(key=lambda cid: self._chunks[cid].chunk_index)

    def delete(self, chunk_ids: list[str]) -> None:
        for cid in chunk_ids:
            chunk = self._chunks.pop(cid, None)
            if chunk is None:
                continue
            bucket = self._by_document.get(chunk.document_id)
            if bucket and cid in bucket:
                bucket.remove(cid)
            if bucket is not None and not bucket:
                self._by_document.pop(chunk.document_id, None)

    def delete_document(self, document_id: str) -> None:
        ids = list(self._by_document.get(document_id, []))
        self.delete(ids)

    def get(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def get_many(self, chunk_ids: list[str]) -> list[Chunk]:
        return [self._chunks[cid] for cid in chunk_ids if cid in self._chunks]

    def list_chunks(self, document_id: str) -> list[Chunk]:
        ids = self._by_document.get(document_id, [])
        return [self._chunks[cid] for cid in ids]

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: IndexFilters | None = None,
    ) -> list[tuple[Chunk, float]]:
        if not self._chunks:
            return []
        scored: list[tuple[Chunk, float]] = []
        for chunk in self._chunks.values():
            if filters is not None and not filters.matches(chunk):
                continue
            if chunk.embedding is None:
                continue
            score = cosine_similarity(query_embedding, chunk.embedding)
            scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(0, top_k)]

    def count(self) -> int:
        return len(self._chunks)

    def list_sources(self) -> list[str]:
        seen: set[str] = set()
        for chunk in self._chunks.values():
            if chunk.source:
                seen.add(chunk.source)
        return sorted(seen)

    def all_chunks(self) -> list[Chunk]:
        """Return every chunk in the store (useful for keyword indexing)."""
        return list(self._chunks.values())
