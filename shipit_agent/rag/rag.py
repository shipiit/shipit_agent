"""The :class:`RAG` facade — the primary user-facing entry point."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .chunker import DocumentChunker, make_document_id
from .embedder import Embedder, coerce_embedder
from .extractors import TextExtractor
from .keyword_store import InMemoryBM25Store, KeywordStore
from .reranker import LLMReranker, Reranker
from .search_pipeline import HybridSearchPipeline
from .types import (
    Chunk,
    Document,
    IndexFilters,
    RAGContext,
    RAGSource,
    SearchQuery,
    SearchResult,
)
from .vector_store import InMemoryVectorStore, VectorStore


@dataclass
class _SourceTracker:
    """Per-run citation index for the source tracker."""

    seen: dict[str, int] = field(default_factory=dict)
    sources: list[RAGSource] = field(default_factory=list)

    def record(self, result: SearchResult) -> None:
        chunk = result.chunk
        if chunk.id in self.seen:
            return
        index = len(self.sources) + 1
        self.seen[chunk.id] = index
        self.sources.append(
            RAGSource(
                index=index,
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                text=chunk.text,
                score=result.score,
                source=chunk.source or chunk.metadata.get("source"),
                metadata=dict(chunk.metadata),
            )
        )

    def record_chunk(self, chunk: Chunk, score: float) -> None:
        if chunk.id in self.seen:
            return
        self.record(SearchResult(chunk=chunk, score=score))


class RAG:
    """The main RAG facade.

    A :class:`RAG` instance owns a :class:`VectorStore`, optional
    :class:`KeywordStore`, an :class:`Embedder`, an optional
    :class:`Reranker`, and a :class:`DocumentChunker`. It exposes
    indexing helpers (``index_text``, ``index_file``, ``index_document``)
    and a query surface (``search``, ``fetch_chunk``, ``list_sources``).

    The instance also tracks every chunk retrieved during an active
    *agent run* through a thread-local :class:`_SourceTracker`. Agents
    call :meth:`begin_run` at the start of a run and
    :meth:`end_run` at the end to collect citations, which are then
    attached to :attr:`shipit_agent.models.AgentResult.rag_sources`.
    """

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedder: Any,
        keyword_store: KeywordStore | None = None,
        reranker: Reranker | None = None,
        chunker: DocumentChunker | None = None,
        auto_embed_on_add: bool = True,
    ) -> None:
        self.vector_store = vector_store
        self.embedder: Embedder = coerce_embedder(embedder)
        self.keyword_store = keyword_store
        self.reranker = reranker
        self.chunker = chunker or DocumentChunker()
        self.auto_embed_on_add = auto_embed_on_add
        self._extractor = TextExtractor()
        self._pipeline = HybridSearchPipeline(
            vector_store=self.vector_store,
            embedder=self.embedder,
            keyword_store=self.keyword_store,
            reranker=self.reranker,
        )
        self._tracker_state = threading.local()

    # ---- factories -------------------------------------------------------

    @classmethod
    def default(cls, *, embedder: Any, reranker: Reranker | None = None) -> "RAG":
        """Build an in-memory RAG with sensible defaults.

        The default setup uses :class:`InMemoryVectorStore`,
        :class:`InMemoryBM25Store`, the user-supplied (or coerced)
        embedder, and a default :class:`DocumentChunker`.
        """
        return cls(
            vector_store=InMemoryVectorStore(),
            keyword_store=InMemoryBM25Store(),
            embedder=embedder,
            reranker=reranker,
        )

    # ---- indexing --------------------------------------------------------

    def index_text(
        self,
        text: str,
        *,
        document_id: str | None = None,
        title: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        # ``source`` is metadata, not identity. When the caller does not
        # supply an explicit ``document_id`` we generate a fresh uuid so
        # multiple ``index_text`` calls sharing a source label do not
        # stomp on each other. Use :meth:`index_file` (or pass
        # ``document_id`` explicitly) to get source-derived, stable ids.
        doc = Document(
            id=document_id or uuid.uuid4().hex,
            content=text,
            title=title,
            source=source,
            metadata=dict(metadata or {}),
            created_at=datetime.now(tz=timezone.utc),
        )
        return self.index_document(doc)

    def index_file(
        self,
        path: str,
        *,
        document_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        content = self._extractor.extract(path)
        if title is None:
            import os

            title = os.path.basename(path)
        return self.index_text(
            content,
            document_id=document_id or make_document_id(path),
            title=title,
            source=path,
            metadata=metadata,
        )

    def index_document(self, document: Document) -> list[Chunk]:
        self.delete_document(document.id)
        chunks = self.chunker.chunk(document)
        if not chunks:
            return []
        if self.auto_embed_on_add:
            texts = [c.text_for_embedding for c in chunks]
            embeddings = self.embedder.embed(texts, kind="passage")
            for chunk, vec in zip(chunks, embeddings):
                chunk.embedding = list(vec)
        self.vector_store.add(chunks)
        if self.keyword_store is not None:
            self.keyword_store.add(chunks)
        return chunks

    def index_documents(self, documents: Iterable[Document]) -> list[Chunk]:
        out: list[Chunk] = []
        for doc in documents:
            out.extend(self.index_document(doc))
        return out

    def reindex(self, document_id: str, *, content: str | None = None) -> list[Chunk]:
        existing = self.vector_store.list_chunks(document_id)
        if not existing and content is None:
            return []
        if content is None:
            content = "\n".join(c.text for c in existing)
        first = existing[0] if existing else None
        return self.index_document(
            Document(
                id=document_id,
                content=content,
                title=first.metadata.get("title") if first else None,
                source=first.source if first else None,
                metadata=dict(first.metadata) if first else {},
                created_at=datetime.now(tz=timezone.utc),
            )
        )

    def delete_document(self, document_id: str) -> None:
        self.vector_store.delete_document(document_id)
        if self.keyword_store is not None:
            self.keyword_store.delete_document(document_id)

    # ---- query -----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: IndexFilters | None = None,
        hybrid_alpha: float = 0.5,
        enable_reranking: bool = False,
        enable_recency_bias: bool = False,
        chunks_above: int = 0,
        chunks_below: int = 0,
    ) -> RAGContext:
        sq = SearchQuery(
            query=query,
            top_k=top_k,
            filters=filters,
            hybrid_alpha=hybrid_alpha,
            enable_reranking=enable_reranking and self.reranker is not None,
            enable_recency_bias=enable_recency_bias,
            chunks_above=chunks_above,
            chunks_below=chunks_below,
        )
        ctx = self._pipeline.search(sq)
        tracker = self._get_tracker()
        if tracker is not None:
            for result in ctx.results:
                tracker.record(result)
        return ctx

    def fetch_chunk(
        self,
        chunk_id: str,
        *,
        chunks_above: int = 0,
        chunks_below: int = 0,
    ) -> Chunk | None:
        chunk = self.vector_store.get(chunk_id)
        if chunk is None:
            return None
        tracker = self._get_tracker()
        if tracker is not None:
            tracker.record_chunk(chunk, score=1.0)
        if chunks_above > 0 or chunks_below > 0:
            neighbours = self.vector_store.list_chunks(chunk.document_id)
            idx_map = {c.id: i for i, c in enumerate(neighbours)}
            center = idx_map.get(chunk.id)
            if center is not None:
                start = max(0, center - chunks_above)
                end = min(len(neighbours), center + chunks_below + 1)
                for neighbour in neighbours[start:end]:
                    if neighbour.id != chunk.id and tracker is not None:
                        tracker.record_chunk(neighbour, score=0.0)
        return chunk

    def list_sources(self) -> list[str]:
        return self.vector_store.list_sources()

    def count(self) -> int:
        return self.vector_store.count()

    # ---- source tracking (agent integration) ----------------------------

    def begin_run(self) -> None:
        """Start a new source-tracking scope for the current thread."""
        self._tracker_state.tracker = _SourceTracker()

    def end_run(self) -> list[RAGSource]:
        """Return (and clear) the sources recorded since :meth:`begin_run`."""
        tracker: _SourceTracker | None = getattr(self._tracker_state, "tracker", None)
        if tracker is None:
            return []
        self._tracker_state.tracker = None
        return list(tracker.sources)

    def current_sources(self) -> list[RAGSource]:
        """Peek at sources captured so far during the current run."""
        tracker: _SourceTracker | None = getattr(self._tracker_state, "tracker", None)
        if tracker is None:
            return []
        return list(tracker.sources)

    def _get_tracker(self) -> _SourceTracker | None:
        return getattr(self._tracker_state, "tracker", None)

    # ---- tool wiring ----------------------------------------------------

    def as_tools(self) -> list[Any]:
        """Return the three RAG tools bound to this instance.

        Imported lazily so the ``shipit_agent.rag`` package can still be
        imported in environments where the agent's tool machinery is not
        available yet.
        """
        from .tools import (
            RAGFetchChunkTool,
            RAGListSourcesTool,
            RAGSearchTool,
        )

        return [
            RAGSearchTool(rag=self),
            RAGFetchChunkTool(rag=self),
            RAGListSourcesTool(rag=self),
        ]

    def prompt_section(self) -> str:
        """Return a short system-prompt addition describing the RAG tools."""
        return (
            "You have access to a RAG knowledge base through the tools "
            "`rag_search`, `rag_fetch_chunk`, and `rag_list_sources`. "
            "When the user asks about facts, documents, code, or past "
            "conversations, call `rag_search` first to ground your answer. "
            "In your final answer, cite sources using [N] markers that "
            "correspond to chunks you used. Never invent a citation."
        )
