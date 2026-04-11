"""Super RAG subsystem for shipit_agent.

A powerful, pluggable retrieval-augmented-generation stack usable by any
:class:`shipit_agent.Agent` or deep agent via the ``rag=`` constructor
parameter. Zero required dependencies beyond the Python standard library;
heavier backends (pgvector, chromadb, qdrant, sentence-transformers) are
imported lazily from :mod:`shipit_agent.rag.adapters`.

See :mod:`shipit_agent.rag.rag` for the main :class:`RAG` facade.
"""

from .chunker import DocumentChunker
from .embedder import CallableEmbedder, Embedder, HashingEmbedder
from .extractors import RAGDependencyError, RAGIngestError, TextExtractor
from .keyword_store import InMemoryBM25Store, KeywordStore
from .rag import RAG
from .reranker import LLMReranker, Reranker
from .search_pipeline import HybridSearchPipeline
from .tools import RAGFetchChunkTool, RAGListSourcesTool, RAGSearchTool
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

__all__ = [
    "RAG",
    "Chunk",
    "Document",
    "DocumentChunker",
    "Embedder",
    "CallableEmbedder",
    "HashingEmbedder",
    "HybridSearchPipeline",
    "IndexFilters",
    "InMemoryBM25Store",
    "InMemoryVectorStore",
    "KeywordStore",
    "LLMReranker",
    "RAGContext",
    "RAGDependencyError",
    "RAGFetchChunkTool",
    "RAGIngestError",
    "RAGListSourcesTool",
    "RAGSearchTool",
    "RAGSource",
    "Reranker",
    "SearchQuery",
    "SearchResult",
    "TextExtractor",
    "VectorStore",
]
