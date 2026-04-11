"""Agent-facing RAG tools.

Each tool follows the :class:`shipit_agent.tools.base.Tool` protocol and
forwards to a bound :class:`RAG` instance. Tools emit JSON payloads with
chunk ids and sources so the agent can cite them in its final answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from shipit_agent.tools.base import ToolContext, ToolOutput

if TYPE_CHECKING:  # pragma: no cover
    from .rag import RAG


def _summarise_result(index: int, result) -> dict[str, Any]:
    chunk = result.chunk
    return {
        "citation": f"[{index}]",
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "source": chunk.source or chunk.metadata.get("source"),
        "score": round(float(result.score), 4),
        "text": chunk.text,
    }


@dataclass
class RAGSearchTool:
    """Agent tool that searches the RAG knowledge base."""

    rag: "RAG"
    name: str = "rag_search"
    description: str = (
        "Search the RAG knowledge base for passages relevant to a natural-"
        "language query. Returns the top matching chunks with their "
        "chunk_id, source, and relevance score. Cite results with [N] markers."
    )
    prompt_instructions: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language search query.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of chunks to return.",
                            "default": 5,
                        },
                        "enable_reranking": {
                            "type": "boolean",
                            "description": "If true, run the LLM reranker over the top candidates.",
                            "default": False,
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def run(
        self,
        context: ToolContext,
        query: str = "",
        top_k: int = 5,
        enable_reranking: bool = False,
    ) -> ToolOutput:
        del context
        if not query:
            return ToolOutput(text=json.dumps({"error": "query is required"}))
        ctx = self.rag.search(query, top_k=top_k, enable_reranking=enable_reranking)
        payload = {
            "query": query,
            "total_found": ctx.total_found,
            "results": [_summarise_result(i, r) for i, r in enumerate(ctx.results, start=1)],
        }
        return ToolOutput(
            text=json.dumps(payload, indent=2),
            metadata={"rag_chunk_ids": [r.chunk.id for r in ctx.results]},
        )


@dataclass
class RAGFetchChunkTool:
    """Agent tool that fetches a chunk by id (optionally with context)."""

    rag: "RAG"
    name: str = "rag_fetch_chunk"
    description: str = (
        "Fetch the full text of a specific RAG chunk by its chunk_id. "
        "Optionally include surrounding chunks via chunks_above / chunks_below."
    )
    prompt_instructions: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {
                            "type": "string",
                            "description": "Chunk identifier returned by rag_search.",
                        },
                        "chunks_above": {
                            "type": "integer",
                            "description": "Number of neighbouring chunks to include above.",
                            "default": 0,
                        },
                        "chunks_below": {
                            "type": "integer",
                            "description": "Number of neighbouring chunks to include below.",
                            "default": 0,
                        },
                    },
                    "required": ["chunk_id"],
                },
            },
        }

    def run(
        self,
        context: ToolContext,
        chunk_id: str = "",
        chunks_above: int = 0,
        chunks_below: int = 0,
    ) -> ToolOutput:
        del context
        if not chunk_id:
            return ToolOutput(text=json.dumps({"error": "chunk_id is required"}))
        chunk = self.rag.fetch_chunk(
            chunk_id,
            chunks_above=chunks_above,
            chunks_below=chunks_below,
        )
        if chunk is None:
            return ToolOutput(text=json.dumps({"error": f"chunk {chunk_id!r} not found"}))
        payload: dict[str, Any] = {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "source": chunk.source,
            "text": chunk.text,
            "metadata": chunk.metadata,
        }
        if chunks_above or chunks_below:
            neighbours = self.rag.vector_store.list_chunks(chunk.document_id)
            idx_map = {c.id: i for i, c in enumerate(neighbours)}
            center = idx_map.get(chunk.id, 0)
            payload["context_above"] = [
                {"chunk_id": c.id, "text": c.text}
                for c in neighbours[max(0, center - chunks_above) : center]
            ]
            payload["context_below"] = [
                {"chunk_id": c.id, "text": c.text}
                for c in neighbours[center + 1 : center + 1 + chunks_below]
            ]
        return ToolOutput(
            text=json.dumps(payload, indent=2),
            metadata={"rag_chunk_ids": [chunk.id]},
        )


@dataclass
class RAGListSourcesTool:
    """Agent tool that lists distinct sources in the RAG knowledge base."""

    rag: "RAG"
    name: str = "rag_list_sources"
    description: str = "List the distinct sources indexed in the RAG knowledge base."
    prompt_instructions: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    def run(self, context: ToolContext) -> ToolOutput:
        del context
        return ToolOutput(
            text=json.dumps({"sources": self.rag.list_sources()}, indent=2),
        )
