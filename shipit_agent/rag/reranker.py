"""Reranker protocol + LLM-as-judge default implementation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .types import Chunk


@runtime_checkable
class Reranker(Protocol):
    """Protocol for reranking a set of candidate chunks against a query."""

    def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int,
    ) -> list[tuple[Chunk, float]]: ...


_RERANK_PROMPT = """You are a strict search relevance judge.

Score each candidate passage from 0 (irrelevant) to 10 (perfect answer) for the query.
Return ONLY a JSON array of the same length as the candidates, containing the integer scores.
No prose. No markdown. Example: [8, 3, 10, 0]

Query: {query}

Candidates:
{candidates}
"""


def _format_candidates(chunks: list[Chunk]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        preview = chunk.text.replace("\n", " ")[:400]
        lines.append(f"[{i}] {preview}")
    return "\n".join(lines)


def _parse_scores(text: str, expected: int) -> list[float]:
    """Extract a JSON list of numeric scores from ``text``.

    Tolerant of trailing text and reasoning tags some models emit.
    """
    cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        return [0.0] * expected
    try:
        raw = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return [0.0] * expected
    scores: list[float] = []
    for value in raw:
        try:
            scores.append(float(value))
        except (TypeError, ValueError):
            scores.append(0.0)
    if len(scores) < expected:
        scores.extend([0.0] * (expected - len(scores)))
    elif len(scores) > expected:
        scores = scores[:expected]
    return scores


@dataclass
class LLMReranker:
    """Reranker that delegates relevance scoring to an LLM.

    ``llm`` must implement ``complete(messages=[Message(...)])`` returning
    an object with a ``.content`` attribute — the same shape
    :class:`shipit_agent.agent.Agent` already consumes.
    """

    llm: Any
    batch_size: int = 10

    def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int,
    ) -> list[tuple[Chunk, float]]:
        if not chunks:
            return []
        from shipit_agent.models import Message

        scored: list[tuple[Chunk, float]] = []
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start : start + self.batch_size]
            prompt = _RERANK_PROMPT.format(
                query=query,
                candidates=_format_candidates(batch),
            )
            response = self.llm.complete(
                messages=[Message(role="user", content=prompt)]
            )
            raw_scores = _parse_scores(
                getattr(response, "content", "") or "", len(batch)
            )
            for chunk, score in zip(batch, raw_scores):
                scored.append((chunk, score / 10.0))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(0, top_k)]
