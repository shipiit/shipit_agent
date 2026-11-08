"""RAG indexing: text, files and documents, reindexing and deletion."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .chunker import make_document_id
from .types import (
    Chunk,
    Document,
)


class _RAGIndexing:
    """RAG indexing: text, files and documents, reindexing and deletion."""

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
