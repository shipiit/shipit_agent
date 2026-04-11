import json

from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.rag import RAG
from shipit_agent.rag.tools import RAGFetchChunkTool, RAGListSourcesTool, RAGSearchTool
from shipit_agent.tools.base import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(prompt="", metadata={}, state={})


def _rag_with_docs() -> RAG:
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("Shipit supports Python 3.10+.", document_id="readme", source="readme")
    rag.index_text(
        "The agent streams events in real time.",
        document_id="streaming",
        source="features",
    )
    return rag


def test_rag_search_tool_schema():
    tool = RAGSearchTool(rag=_rag_with_docs())
    schema = tool.schema()
    # OpenAI/LiteLLM-compatible function-call schema shape
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "rag_search"
    assert fn["name"], "function name must be non-empty (Bedrock rejects empty)"
    assert fn["description"], "function description must be non-empty"
    assert "query" in fn["parameters"]["properties"]
    assert "required" in fn["parameters"]
    assert "query" in fn["parameters"]["required"]


def test_rag_search_tool_returns_json_with_citations():
    tool = RAGSearchTool(rag=_rag_with_docs())
    output = tool.run(_ctx(), query="python version", top_k=1)
    payload = json.loads(output.text)
    assert payload["query"] == "python version"
    assert payload["total_found"] >= 1
    assert payload["results"][0]["citation"].startswith("[")
    assert "chunk_id" in payload["results"][0]
    assert "source" in payload["results"][0]
    assert "rag_chunk_ids" in output.metadata


def test_rag_search_tool_missing_query_returns_error():
    tool = RAGSearchTool(rag=_rag_with_docs())
    output = tool.run(_ctx(), query="")
    payload = json.loads(output.text)
    assert "error" in payload


def test_rag_fetch_chunk_tool_returns_chunk():
    rag = _rag_with_docs()
    tool = RAGFetchChunkTool(rag=rag)
    # Find an existing chunk id
    any_chunk = next(iter(rag.vector_store.all_chunks()))
    output = tool.run(_ctx(), chunk_id=any_chunk.id)
    payload = json.loads(output.text)
    assert payload["chunk_id"] == any_chunk.id
    assert payload["text"] == any_chunk.text


def test_rag_fetch_chunk_missing_returns_error():
    tool = RAGFetchChunkTool(rag=_rag_with_docs())
    output = tool.run(_ctx(), chunk_id="does-not-exist")
    payload = json.loads(output.text)
    assert "error" in payload


def test_rag_fetch_chunk_with_context():
    rag = RAG.default(embedder=HashingEmbedder(dimension=128))
    rag.index_text(
        "First paragraph. Second paragraph. Third paragraph.",
        document_id="multi",
    )
    tool = RAGFetchChunkTool(rag=rag)
    # Single chunk document so context_above/below will be empty but keys exist.
    output = tool.run(_ctx(), chunk_id="multi::0", chunks_above=1, chunks_below=1)
    payload = json.loads(output.text)
    assert "context_above" in payload
    assert "context_below" in payload


def test_rag_list_sources_tool():
    tool = RAGListSourcesTool(rag=_rag_with_docs())
    output = tool.run(_ctx())
    payload = json.loads(output.text)
    assert set(payload["sources"]) == {"readme", "features"}


def test_rag_search_tracks_sources_during_run():
    rag = _rag_with_docs()
    tool = RAGSearchTool(rag=rag)
    rag.begin_run()
    tool.run(_ctx(), query="python", top_k=2)
    tool.run(_ctx(), query="streams", top_k=2)
    sources = rag.end_run()
    # At least one source captured
    assert sources
    assert all(s.index > 0 for s in sources)
