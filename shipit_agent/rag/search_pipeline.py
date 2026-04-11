"""Hybrid search pipeline.

Combines vector + keyword retrieval via Reciprocal Rank Fusion (RRF),
optionally applies recency bias, reranking, and pulls neighbouring
chunks from the same document for context expansion.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .embedder import Embedder
from .keyword_store import KeywordStore
from .reranker import Reranker
from .types import Chunk, IndexFilters, RAGContext, SearchQuery, SearchResult
from .vector_store import VectorStore


_RRF_K = 60.0


def _rrf_score(rank: int) -> float:
    return 1.0 / (_RRF_K + rank)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _recency_multiplier(created_at: datetime | None, half_life_days: float) -> float:
    if created_at is None or half_life_days <= 0:
        return 1.0
    age = _now() - _ensure_aware(created_at)
    age_days = max(age.total_seconds(), 0.0) / 86400.0
    return math.exp(-age_days / half_life_days)


@dataclass
class HybridSearchPipeline:
    """Orchestrates vector + keyword retrieval, RRF fusion, and post-processing."""

    vector_store: VectorStore
    embedder: Embedder
    keyword_store: KeywordStore | None = None
    reranker: Reranker | None = None

    def search(self, query: SearchQuery) -> RAGContext:
        timings: dict[str, float] = {}
        total_start = time.perf_counter()

        # 1. Embed the query.
        t0 = time.perf_counter()
        query_embedding = self.embedder.embed([query.query], kind="query")[0]
        timings["embed_ms"] = (time.perf_counter() - t0) * 1000

        # 2. & 3. Vector + keyword search (in parallel when both configured).
        top_n = max(query.top_k * 2, query.top_k)
        vec_results: list[tuple[Chunk, float]] = []
        kw_results: list[tuple[Chunk, float]] = []

        def _vec() -> list[tuple[Chunk, float]]:
            t = time.perf_counter()
            out = self.vector_store.search(
                query_embedding, top_n, filters=query.filters
            )
            timings["vector_ms"] = (time.perf_counter() - t) * 1000
            return out

        def _kw() -> list[tuple[Chunk, float]]:
            t = time.perf_counter()
            assert self.keyword_store is not None
            out = self.keyword_store.search(query.query, top_n, filters=query.filters)
            timings["keyword_ms"] = (time.perf_counter() - t) * 1000
            return out

        if self.keyword_store is not None:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_vec = pool.submit(_vec)
                fut_kw = pool.submit(_kw)
                vec_results = fut_vec.result()
                kw_results = fut_kw.result()
        else:
            vec_results = _vec()

        # 4. RRF fusion.
        fused: dict[str, dict[str, Any]] = {}
        alpha = max(0.0, min(1.0, query.hybrid_alpha))
        for rank, (chunk, raw_score) in enumerate(vec_results):
            entry = fused.setdefault(
                chunk.id,
                {
                    "chunk": chunk,
                    "vector_score": None,
                    "keyword_score": None,
                    "score": 0.0,
                },
            )
            entry["vector_score"] = raw_score
            entry["score"] += alpha * _rrf_score(rank)
        if kw_results:
            for rank, (chunk, raw_score) in enumerate(kw_results):
                entry = fused.setdefault(
                    chunk.id,
                    {
                        "chunk": chunk,
                        "vector_score": None,
                        "keyword_score": None,
                        "score": 0.0,
                    },
                )
                entry["keyword_score"] = raw_score
                entry["score"] += (1.0 - alpha) * _rrf_score(rank)

        fused_list = list(fused.values())
        fused_list.sort(key=lambda e: e["score"], reverse=True)

        # 5. Optional recency bias.
        if query.enable_recency_bias:
            for entry in fused_list:
                entry["score"] *= _recency_multiplier(
                    entry["chunk"].created_at,
                    query.recency_half_life_days,
                )
            fused_list.sort(key=lambda e: e["score"], reverse=True)

        # 6. Optional reranking over the top 2*k candidates.
        rerank_scores: dict[str, float] = {}
        if query.enable_reranking and self.reranker is not None and fused_list:
            t = time.perf_counter()
            candidates = [entry["chunk"] for entry in fused_list[: query.top_k * 2]]
            reranked = self.reranker.rerank(
                query.query, candidates, top_k=len(candidates)
            )
            ordering = {chunk.id: idx for idx, (chunk, _) in enumerate(reranked)}
            rerank_scores = {chunk.id: score for chunk, score in reranked}
            fused_list = sorted(
                [e for e in fused_list if e["chunk"].id in ordering],
                key=lambda e: ordering[e["chunk"].id],
            )
            timings["rerank_ms"] = (time.perf_counter() - t) * 1000

        # 7. Build SearchResults + context expansion.
        final_entries = fused_list[: query.top_k]
        results: list[SearchResult] = []
        for entry in final_entries:
            chunk: Chunk = entry["chunk"]
            expanded_above, expanded_below = self._expand_context(
                chunk,
                query.chunks_above,
                query.chunks_below,
            )
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=float(entry["score"]),
                    vector_score=entry["vector_score"],
                    keyword_score=entry["keyword_score"],
                    rerank_score=rerank_scores.get(chunk.id),
                    expanded_above=expanded_above,
                    expanded_below=expanded_below,
                )
            )

        timings["total_ms"] = (time.perf_counter() - total_start) * 1000
        return RAGContext(
            query=query.query,
            results=results,
            total_found=len(fused_list),
            timing_ms=timings,
        )

    def _expand_context(
        self,
        chunk: Chunk,
        above: int,
        below: int,
    ) -> tuple[list[Chunk], list[Chunk]]:
        if above <= 0 and below <= 0:
            return [], []
        neighbours = self.vector_store.list_chunks(chunk.document_id)
        if not neighbours:
            return [], []
        idx_map = {c.id: i for i, c in enumerate(neighbours)}
        center = idx_map.get(chunk.id)
        if center is None:
            return [], []
        start = max(0, center - above)
        end = min(len(neighbours), center + below + 1)
        expanded_above = neighbours[start:center]
        expanded_below = neighbours[center + 1 : end]
        return expanded_above, expanded_below


__all__ = [
    "HybridSearchPipeline",
    "IndexFilters",
    "SearchQuery",
]
