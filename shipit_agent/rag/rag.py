"""The :class:`RAG` facade — the primary user-facing entry point."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .chunker import DocumentChunker
from .embedder import Embedder, coerce_embedder
from .extractors import TextExtractor
from .indexing import _RAGIndexing
from .keyword_store import InMemoryBM25Store, KeywordStore
from .reranker import Reranker
from .search_pipeline import HybridSearchPipeline
from .types import (
    Chunk,
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

    def record(self, result: SearchResult) -> int:
        """Track *result*; returns its citation number for this run."""
        chunk = result.chunk
        if chunk.id in self.seen:
            return self.seen[chunk.id]
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
        return index

    def record_chunk(self, chunk: Chunk, score: float) -> int:
        return self.record(SearchResult(chunk=chunk, score=score))


class RAG(_RAGIndexing):
    """The main RAG facade.

    A :class:`RAG` instance owns a :class:`VectorStore`, optional
    :class:`KeywordStore`, an :class:`Embedder`, an optional
    :class:`Reranker`, and a :class:`DocumentChunker`. It exposes
    indexing helpers (``index_text``, ``index_file``, ``index_document``)
    and a query surface (``search``, ``fetch_chunk``, ``list_sources``).

    The instance also tracks every chunk retrieved during an active
    *agent run* through a per-run :class:`_SourceTracker`. Agents
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
        # A context variable, not a thread-local: the agent loop runs on a
        # worker thread that inherits the caller's context, so a thread-local
        # set in begin_run() was invisible to the tools. Each concurrent run
        # still gets its own tracker, because each begin_run() sets it in
        # that run's own context.
        self._tracker: ContextVar[_SourceTracker | None] = ContextVar(
            f"shipit_rag_tracker_{id(self)}", default=None
        )

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
        """Start a new source-tracking scope for the current run."""
        self._tracker.set(_SourceTracker())

    def end_run(self) -> list[RAGSource]:
        """Return (and clear) the sources recorded since :meth:`begin_run`."""
        tracker = self._tracker.get()
        if tracker is None:
            return []
        self._tracker.set(None)
        return list(tracker.sources)

    def current_sources(self) -> list[RAGSource]:
        """Peek at sources captured so far during the current run."""
        tracker = self._tracker.get()
        if tracker is None:
            return []
        return list(tracker.sources)

    def citation_index(self, chunk_id: str) -> int | None:
        """The [N] this run gave *chunk_id*, or ``None`` outside a run or if unseen."""
        tracker = self._tracker.get()
        if tracker is None:
            return None
        return tracker.seen.get(chunk_id)

    def _get_tracker(self) -> _SourceTracker | None:
        return self._tracker.get()

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
