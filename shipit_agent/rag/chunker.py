"""Sentence-aware Onyx-style chunker.

Produces :class:`Chunk` instances with a title prefix and metadata suffix
baked into ``text_for_embedding`` so retrieval quality remains high even
without a dedicated title-embedding stream.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Iterable

from .types import Chunk, Document


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[\(\"'])")
_WHITESPACE = re.compile(r"\s+")


def _approx_tokens(text: str) -> int:
    """Return an approximate token count.

    Uses the same 4-char-per-token heuristic as
    :mod:`shipit_agent.context_tracker`.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_END.split(text)
    cleaned: list[str] = []
    for part in parts:
        normalised = _WHITESPACE.sub(" ", part).strip()
        if normalised:
            cleaned.append(normalised)
    return cleaned


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    """Split an oversized sentence into fixed-width pieces."""
    return [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)]


@dataclass
class DocumentChunker:
    """Greedy sentence-based chunker.

    Attributes:
        target_tokens: Preferred chunk size in approximate tokens.
        overlap_tokens: Overlap between consecutive chunks in approximate tokens.
        title_prefix_chars: Number of leading title characters prepended to
            ``text_for_embedding`` on every chunk.
    """

    target_tokens: int = 512
    overlap_tokens: int = 64
    title_prefix_chars: int = 64

    def chunk(self, document: Document) -> list[Chunk]:
        content = (document.content or "").strip()
        if not content:
            return []

        target_chars = self.target_tokens * 4
        overlap_chars = self.overlap_tokens * 4
        sentences = _split_sentences(content)
        if not sentences:
            return []

        raw_chunks: list[tuple[int, int, str]] = []  # (start_char, end_char, text)
        cursor = 0
        buffer_parts: list[str] = []
        buffer_start = 0
        buffer_len = 0

        def flush() -> None:
            nonlocal buffer_parts, buffer_start, buffer_len
            if not buffer_parts:
                return
            text = " ".join(buffer_parts).strip()
            if text:
                raw_chunks.append((buffer_start, buffer_start + len(text), text))
            buffer_parts = []
            buffer_len = 0

        for sentence in sentences:
            start_in_doc = content.find(sentence, cursor)
            if start_in_doc < 0:
                start_in_doc = cursor
            cursor = start_in_doc + len(sentence)

            if len(sentence) > target_chars:
                flush()
                for piece in _hard_split(sentence, target_chars):
                    piece_start = content.find(piece, max(0, start_in_doc))
                    if piece_start < 0:
                        piece_start = start_in_doc
                    raw_chunks.append((piece_start, piece_start + len(piece), piece))
                continue

            projected = buffer_len + (1 if buffer_parts else 0) + len(sentence)
            if buffer_parts and projected > target_chars:
                flush()
                buffer_start = start_in_doc

            if not buffer_parts:
                buffer_start = start_in_doc
            buffer_parts.append(sentence)
            buffer_len = projected

        flush()

        if not raw_chunks:
            return []

        # Apply overlap by stitching the tail of the previous chunk onto the
        # head of the next. Overlap is character-based so the underlying
        # text still matches the document.
        if overlap_chars > 0 and len(raw_chunks) > 1:
            stitched: list[tuple[int, int, str]] = []
            for idx, (start, end, text) in enumerate(raw_chunks):
                if idx == 0:
                    stitched.append((start, end, text))
                    continue
                prev_text = raw_chunks[idx - 1][2]
                tail = prev_text[-overlap_chars:]
                # Avoid duplicating text if the prev chunk already covers us.
                stitched.append((max(0, start - len(tail)), end, f"{tail} {text}".strip()))
            raw_chunks = stitched

        title_prefix = ""
        if document.title:
            title_prefix = document.title[: self.title_prefix_chars].strip()

        metadata_suffix = self._build_metadata_suffix(document)

        chunks: list[Chunk] = []
        for index, (start, end, text) in enumerate(raw_chunks):
            chunk_id = f"{document.id}::{index}"
            text_for_embedding = text
            if title_prefix:
                text_for_embedding = f"{title_prefix}\n{text_for_embedding}"
            if metadata_suffix:
                text_for_embedding = f"{text_for_embedding}\n{metadata_suffix}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    document_id=document.id,
                    chunk_index=index,
                    text=text,
                    text_for_embedding=text_for_embedding,
                    metadata=dict(document.metadata),
                    source=document.source,
                    start_char=start,
                    end_char=end,
                    created_at=document.created_at,
                )
            )
        return chunks

    def chunk_many(self, documents: Iterable[Document]) -> list[Chunk]:
        out: list[Chunk] = []
        for doc in documents:
            out.extend(self.chunk(doc))
        return out

    @staticmethod
    def _build_metadata_suffix(document: Document) -> str:
        parts: list[str] = []
        if document.source:
            parts.append(f"Source: {document.source}")
        tags = document.metadata.get("tags") if document.metadata else None
        if tags:
            if isinstance(tags, (list, tuple)):
                parts.append("Tags: " + ", ".join(str(t) for t in tags))
            else:
                parts.append(f"Tags: {tags}")
        if not parts:
            return ""
        return " | ".join(parts)


def make_document_id(source: str | None = None) -> str:
    """Generate a stable-ish document id from a source or a random uuid."""
    if source:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source)
        return safe[:200] or uuid.uuid4().hex
    return uuid.uuid4().hex
