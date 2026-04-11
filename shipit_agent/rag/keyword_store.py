"""Keyword store protocol and pure-Python BM25 implementation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .types import Chunk, IndexFilters


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "it",
        "at",
        "as",
        "by",
        "from",
        "but",
        "not",
        "no",
    }
)


def _tokenize(text: str) -> list[str]:
    return [
        t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS
    ]


@runtime_checkable
class KeywordStore(Protocol):
    """Protocol for keyword-based search backends."""

    def add(self, chunks: list[Chunk]) -> None: ...

    def delete(self, chunk_ids: list[str]) -> None: ...

    def delete_document(self, document_id: str) -> None: ...

    def search(
        self,
        query: str,
        top_k: int,
        filters: IndexFilters | None = None,
    ) -> list[tuple[Chunk, float]]: ...

    def count(self) -> int: ...


@dataclass
class InMemoryBM25Store:
    """Simple in-memory BM25 index — no external deps.

    This is a straightforward implementation of BM25 with ``k1=1.5`` and
    ``b=0.75`` defaults. Accuracy is sufficient for hybrid retrieval on
    small-to-medium corpora (say, under 100k chunks).
    """

    k1: float = 1.5
    b: float = 0.75
    _chunks: dict[str, Chunk] = field(default_factory=dict)
    _token_lists: dict[str, list[str]] = field(default_factory=dict)
    _doc_freq: dict[str, int] = field(default_factory=dict)
    _avg_len: float = 0.0
    _dirty: bool = False

    def add(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            previous = self._token_lists.get(chunk.id)
            if previous is not None:
                for tok in set(previous):
                    self._doc_freq[tok] -= 1
                    if self._doc_freq[tok] <= 0:
                        self._doc_freq.pop(tok, None)
            tokens = _tokenize(chunk.text_for_embedding or chunk.text)
            self._chunks[chunk.id] = chunk
            self._token_lists[chunk.id] = tokens
            for tok in set(tokens):
                self._doc_freq[tok] = self._doc_freq.get(tok, 0) + 1
        self._dirty = True

    def delete(self, chunk_ids: list[str]) -> None:
        for cid in chunk_ids:
            tokens = self._token_lists.pop(cid, None)
            self._chunks.pop(cid, None)
            if tokens:
                for tok in set(tokens):
                    self._doc_freq[tok] = self._doc_freq.get(tok, 0) - 1
                    if self._doc_freq[tok] <= 0:
                        self._doc_freq.pop(tok, None)
        self._dirty = True

    def delete_document(self, document_id: str) -> None:
        ids = [cid for cid, c in self._chunks.items() if c.document_id == document_id]
        self.delete(ids)

    def _recompute_avg(self) -> None:
        if not self._token_lists:
            self._avg_len = 0.0
        else:
            self._avg_len = sum(len(t) for t in self._token_lists.values()) / len(
                self._token_lists
            )
        self._dirty = False

    def search(
        self,
        query: str,
        top_k: int,
        filters: IndexFilters | None = None,
    ) -> list[tuple[Chunk, float]]:
        if not self._chunks:
            return []
        if self._dirty:
            self._recompute_avg()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        n = len(self._token_lists)
        scored: list[tuple[Chunk, float]] = []
        for cid, tokens in self._token_lists.items():
            chunk = self._chunks[cid]
            if filters is not None and not filters.matches(chunk):
                continue
            if not tokens:
                continue
            score = 0.0
            dl = len(tokens)
            freq_map: dict[str, int] = {}
            for t in tokens:
                freq_map[t] = freq_map.get(t, 0) + 1
            for qt in query_tokens:
                df = self._doc_freq.get(qt, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                f = freq_map.get(qt, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (
                    1 - self.b + self.b * dl / (self._avg_len or 1.0)
                )
                score += idf * (f * (self.k1 + 1)) / denom
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(0, top_k)]

    def count(self) -> int:
        return len(self._chunks)
