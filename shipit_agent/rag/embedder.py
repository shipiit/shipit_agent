"""Embedder protocol and zero-dependency implementations.

The default :class:`HashingEmbedder` produces deterministic, stdlib-only
embeddings suitable for tests, local development, and offline demos. Real
workloads should plug in a production embedder through
:class:`CallableEmbedder` or one of the provider-specific adapters in
:mod:`shipit_agent.rag.adapters`.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding backends.

    Implementations must expose a stable ``dimension`` attribute and embed
    passages and queries symmetrically. The optional ``kind`` argument
    lets implementations apply asymmetric transforms (e.g. query
    prefixes) when supported.
    """

    dimension: int

    def embed(
        self, texts: list[str], *, kind: str = "passage"
    ) -> list[list[float]]: ...


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


@dataclass
class HashingEmbedder:
    """Deterministic feature-hashing embedder.

    Produces L2-normalised vectors via sha256 bucketing. Two texts sharing
    many tokens will have high cosine similarity; unrelated texts tend
    towards zero. Suitable for tests and offline use, not for production
    retrieval quality.
    """

    dimension: int = 384
    seed: str = "shipit-rag"

    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        del kind  # symmetric
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(f"{self.seed}:{token}".encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        return _normalize(vec)


@dataclass
class CallableEmbedder:
    """Wrap a user-supplied ``fn(list[str]) -> list[list[float]]``."""

    fn: Callable[[list[str]], list[list[float]]]
    dimension: int

    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        del kind
        vectors = list(self.fn(list(texts)))
        if len(vectors) != len(texts):
            raise ValueError(
                f"CallableEmbedder returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        for vec in vectors:
            if len(vec) != self.dimension:
                raise ValueError(
                    f"CallableEmbedder produced dim={len(vec)}, expected {self.dimension}"
                )
        return vectors


def coerce_embedder(obj: Any) -> Embedder:
    """Return an :class:`Embedder` from a user-supplied object.

    Accepts:

    - An already-conforming :class:`Embedder` instance.
    - A plain callable ``fn(list[str]) -> list[list[float]]`` (wrapped in
      :class:`CallableEmbedder` by probing one sample for the dimension).
    - Anything else → falls back to :class:`HashingEmbedder` with a
      default 384-dim output and a short warning logged via the
      ``warnings`` module.
    """
    import warnings

    if isinstance(obj, Embedder):
        return obj
    if callable(obj):
        try:
            probe = obj(["__probe__"])
            dim = len(probe[0])
        except Exception:  # pragma: no cover - defensive
            warnings.warn(
                "coerce_embedder: callable failed the probe; falling back to HashingEmbedder",
                RuntimeWarning,
                stacklevel=2,
            )
            return HashingEmbedder()
        return CallableEmbedder(fn=obj, dimension=dim)
    warnings.warn(
        "coerce_embedder: object is not an Embedder or callable; falling back to HashingEmbedder",
        RuntimeWarning,
        stacklevel=2,
    )
    return HashingEmbedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
