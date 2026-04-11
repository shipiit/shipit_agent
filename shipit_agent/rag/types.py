"""Core data types for the shipit_agent RAG subsystem."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Document:
    """A source document before chunking."""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    title: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": dict(self.metadata),
            "source": self.source,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Chunk:
    """A single retrievable chunk of a document."""

    id: str
    document_id: str
    chunk_index: int
    text: str
    text_for_embedding: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    start_char: int = 0
    end_char: int = 0
    embedding: list[float] | None = None
    title_embedding: list[float] | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.text_for_embedding:
            self.text_for_embedding = self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "metadata": dict(self.metadata),
            "source": self.source,
            "start_char": self.start_char,
            "end_char": self.end_char,
        }


@dataclass
class IndexFilters:
    """Filters applied to vector/keyword search."""

    document_ids: list[str] | None = None
    sources: list[str] | None = None
    metadata_match: dict[str, Any] | None = None
    time_min: datetime | None = None
    time_max: datetime | None = None

    def matches(self, chunk: Chunk) -> bool:
        """Return True if ``chunk`` satisfies all configured filters."""
        if self.document_ids is not None and chunk.document_id not in self.document_ids:
            return False
        if self.sources is not None and chunk.source not in self.sources:
            return False
        if self.metadata_match:
            for key, expected in self.metadata_match.items():
                if chunk.metadata.get(key) != expected:
                    return False
        if self.time_min or self.time_max:
            created = chunk.created_at
            if created is None:
                return False
            if self.time_min and created < self.time_min:
                return False
            if self.time_max and created > self.time_max:
                return False
        return True


@dataclass
class SearchQuery:
    """A query submitted to the hybrid search pipeline."""

    query: str
    top_k: int = 10
    filters: IndexFilters | None = None
    hybrid_alpha: float = 0.5
    enable_reranking: bool = False
    enable_recency_bias: bool = False
    recency_half_life_days: float = 30.0
    chunks_above: int = 0
    chunks_below: int = 0


@dataclass
class SearchResult:
    """A ranked chunk returned by the search pipeline."""

    chunk: Chunk
    score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    expanded_above: list[Chunk] = field(default_factory=list)
    expanded_below: list[Chunk] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.chunk.to_dict(),
            "score": self.score,
            "vector_score": self.vector_score,
            "keyword_score": self.keyword_score,
            "rerank_score": self.rerank_score,
            "expanded_above": [c.to_dict() for c in self.expanded_above],
            "expanded_below": [c.to_dict() for c in self.expanded_below],
        }


@dataclass
class RAGContext:
    """A RAG search response."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_found: int = 0
    timing_ms: dict[str, float] = field(default_factory=dict)

    def to_prompt_context(self, max_chars: int = 8000) -> str:
        """Format the results as a prompt-ready context block.

        Each chunk is rendered as:
            [1] source=readme | chunk_id=readme::0
                Shipit supports Python 3.10+.

        The [N] indices are stable and match citation markers the SourceTracker
        will attach to the ``AgentResult``.
        """
        if not self.results:
            return f"(no results for query: {self.query!r})"

        lines: list[str] = []
        remaining = max_chars
        for i, result in enumerate(self.results, start=1):
            chunk = result.chunk
            src = chunk.source or chunk.metadata.get("source") or "unknown"
            header = f"[{i}] source={src} | chunk_id={chunk.id}"
            body = chunk.text.strip()
            entry = f"{header}\n    {body}"
            if len(entry) > remaining:
                if remaining <= len(header) + 5:
                    break
                entry = f"{header}\n    {body[: max(0, remaining - len(header) - 10)]}…"
            lines.append(entry)
            remaining -= len(entry) + 1
            if remaining <= 0:
                break
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_found": self.total_found,
            "timing_ms": dict(self.timing_ms),
        }


@dataclass
class RAGSource:
    """A source citation attached to an AgentResult after a RAG-backed run."""

    index: int
    chunk_id: str
    document_id: str
    text: str
    score: float
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "score": self.score,
            "source": self.source,
            "metadata": dict(self.metadata),
        }
