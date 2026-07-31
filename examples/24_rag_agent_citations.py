"""
24 — RAG + Agent: hybrid retrieval with citations, end to end.

The full Super-RAG path in one clean example, fully offline:

    index      →  DocumentChunker (budgeted overlap — chunks never overflow
                  the embedder window) + HashingEmbedder
    retrieve   →  hybrid vector + BM25, fused with Reciprocal Rank Fusion
                  (1/(60+rank), component scores preserved)
    answer     →  Agent(rag=...) — the model grounds itself via the
                  rag_search tool; retrieved chunks surface on
                  result.rag_sources for citation rendering

Swap HashingEmbedder for a real embedder (sentence-transformers, OpenAI)
and the scripted LLM for any provider — the pipeline is identical.

Run:
    python examples/24_rag_agent_citations.py
"""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.rag import RAG, HashingEmbedder

DOCS = {
    "billing-policy": (
        "Refunds are issued within 14 days of purchase. Annual plans are "
        "refunded pro-rata after the first month. Enterprise contracts "
        "follow the negotiated terms in the master agreement. "
        "Chargebacks suspend the account until resolved."
    ),
    "support-runbook": (
        "Priority-1 incidents page the on-call engineer immediately. "
        "Customers on the Scale tier get a 30-minute response SLA. "
        "All refund escalations route to the billing team, never support."
    ),
    "product-faq": (
        "The Scale tier includes SSO, audit logs, and unlimited seats. "
        "Downgrades take effect at the next billing cycle."
    ),
}


class GroundedLLM:
    """Offline stand-in that follows the real RAG flow: call `rag_search`
    first, then answer strictly from what retrieval returned."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools=None, **_kwargs) -> LLMResponse:
        from shipit_agent.llms.base import ToolCall

        self.turn += 1
        if self.turn == 1:
            return LLMResponse(tool_calls=[ToolCall(
                name="rag_search",
                arguments={"query": "refund policy annual plans escalation"},
            )])
        context = " ".join(
            (m.get("content") if isinstance(m, dict) else m.content) or ""
            for m in messages
        )
        if "pro-rata" in context:
            return LLMResponse(content=(
                "Refunds are issued within 14 days of purchase; annual plans "
                "are pro-rata after the first month [billing-policy]. Refund "
                "escalations go to the billing team [support-runbook]."
            ))
        return LLMResponse(content="I could not find that in the documents.")


def main() -> None:
    # 1 · Index — chunking uses the budgeted overlap: carried overlap is
    #     capped by the room left under the chunk target, so no chunk ever
    #     exceeds the embedder window.
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    for doc_id, text in DOCS.items():
        rag.index_text(text, document_id=doc_id, title=doc_id)
    print(f"indexed {len(DOCS)} documents\n")

    # 2 · Retrieval — hybrid vector + BM25, RRF-fused.
    hits = rag.search("refund policy for annual plans")
    print("top hits (RRF-fused):")
    for result_item in hits.results[:3]:
        chunk = result_item.chunk
        print(f"  [{chunk.document_id}] score={result_item.score:.4f} "
              f"— {chunk.text[:60]}…")
    print()

    # 3 · Agent — RAG attaches as tools (rag_search / rag_fetch_chunk /
    #     rag_list_sources); the model calls rag_search to ground itself and
    #     every retrieved chunk surfaces on result.rag_sources for citations.
    agent = Agent(llm=GroundedLLM(), rag=rag, auto_use_skills=False)
    result = agent.run("What is the refund policy for annual plans, and who "
                       "handles refund escalations?")
    print("answer:", result.output)
    print("\ncited sources:")
    for source in result.rag_sources:
        doc = getattr(source, "document_id", source)
        print(f"  • {doc}")


if __name__ == "__main__":
    main()
