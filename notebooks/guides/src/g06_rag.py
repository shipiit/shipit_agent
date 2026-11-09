"""Guide 06: RAG from first index to cited agent answers."""

from cells import code, md

TITLE = "RAG: search your documents, cite the passages"

CELLS = [
    md("""
    # Guide 06 · RAG: search your documents, cite the passages

    Retrieval-augmented generation answers from *your* documents. shipit's RAG indexes text and files into
    chunks, searches them with vectors and keywords together, and gives an agent search tools plus the
    instructions to cite what it used.

    **What you'll learn**

    1. Index text and files, and what a chunk is
    2. Search: scores, hybrid weighting, filters and neighbouring chunks
    3. Offline embeddings versus real ones (Amazon Titan on Bedrock)
    4. Reranking with a model
    5. Keeping the index current: reindex and delete
    6. Giving it to an agent, and reading the cited sources
    7. The same RAG on Haiku 5.5 (Anthropic) and Gemma 4

    Every output below is real.
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · A small knowledge base

    Four policy documents for a fictional billing product, written to a `kb/` folder so the guide can index
    real files. A file's path is its source, so keep paths short and stable.
    """),
    code("""
    from pathlib import Path

    DOCS = {
        "refunds.md": \"\"\"# Refund policy
    Customers can request a full refund within 30 days of a charge. After 30 days, refunds are prorated
    by unused days. Refunds go back to the original payment method and take 5 to 10 business days.
    Annual plans cancelled after 90 days are not refundable, but stay active until the term ends.\"\"\",
        "plans.md": \"\"\"# Plans and pricing
    Starter costs $12 per seat per month and includes 3 projects. Team costs $29 per seat per month with
    unlimited projects and SSO. Enterprise is priced per contract and adds audit logs, a 99.95% uptime SLA
    and a named support engineer. Annual billing saves two months on every plan.\"\"\",
        "security.md": \"\"\"# Security
    All data is encrypted at rest with AES-256 and in transit with TLS 1.3. Customer data stays in the
    region chosen at signup: EU (Frankfurt) or US (Virginia). Access to production needs hardware keys,
    and every access is logged and reviewed weekly. We run a third-party penetration test twice a year.\"\"\",
        "support.md": \"\"\"# Support
    Starter gets email support with a 2 business day response. Team gets chat and email with a 4 hour
    response during business hours. Enterprise gets 24/7 phone support with a 1 hour response for
    severity-1 incidents. Status updates are posted at status.example.com.\"\"\",
    }

    folder = Path("kb")
    folder.mkdir(exist_ok=True)
    for name, text in DOCS.items():
        (folder / name).write_text(text)
    print(sorted(p.name for p in folder.iterdir()))
    """),
    md("""
    ## 3 · An index with offline embeddings

    `RAG.default(embedder=...)` builds an in-memory vector store and an in-memory BM25 keyword store.
    `HashingEmbedder` needs no network or key: it hashes words into a vector, so it's fast and deterministic,
    but it matches words rather than meaning. Good for tests and for keyword-heavy text.
    """),
    code("""
    from shipit_agent.rag import RAG, HashingEmbedder

    rag = RAG.default(embedder=HashingEmbedder(dimension=512))
    for path in sorted(folder.glob("*.md")):
        chunks = rag.index_file(str(path))
        print(f"{path.name:12} {len(chunks)} chunk(s)")
    print("chunks in the index:", rag.count())
    print("sources:", rag.list_sources())
    """),
    md("""
    ## 4 · What a chunk is

    Each document is split into chunks, the unit that search returns. A chunk keeps its text, its position
    in the document, its source and metadata.
    """),
    code("""
    chunk = rag.index_text(
        "Invoices are emailed on the 1st of each month and can be downloaded as PDF from Settings > Billing.",
        source="invoices.md", title="Invoices", metadata={"team": "billing"},
    )[0]
    print("id:      ", chunk.id)
    print("document:", chunk.document_id, "| index:", chunk.chunk_index, "| chars:", chunk.start_char, "-", chunk.end_char)
    print("source:  ", chunk.source, "| metadata:", chunk.metadata)
    print("text:    ", chunk.text)
    """),
    md("""
    ## 5 · Chunk size

    `DocumentChunker(target_tokens, overlap_tokens)` controls the split. Smaller chunks give more precise
    hits; overlap keeps a sentence that straddles a boundary findable from both sides.
    """),
    code("""
    from shipit_agent.rag import DocumentChunker, InMemoryBM25Store, InMemoryVectorStore

    long_text = " ".join(DOCS.values())
    for target in (512, 64, 32):
        small = RAG(vector_store=InMemoryVectorStore(), keyword_store=InMemoryBM25Store(),
                    embedder=HashingEmbedder(dimension=256),
                    chunker=DocumentChunker(target_tokens=target, overlap_tokens=target // 8))
        print(f"target_tokens={target:3} -> {len(small.index_text(long_text, source='all.md'))} chunks")
    """),
    md("""
    ## 6 · Search

    `search()` returns a `RAGContext`: the results, best first. Each has the vector similarity and the BM25
    keyword score behind it, and a combined `score` that fuses the two by rank (so it orders results; it
    isn't a similarity).
    """),
    code("""
    context = rag.search("how long does a refund take", top_k=3)
    print(f"{context.total_found} found in {context.timing_ms['total_ms']:.2f} ms", {k: round(v, 3) for k, v in context.timing_ms.items()})
    def fmt(score) -> str:
        return "  -  " if score is None else f"{score:.3f}"   # None: that search didn't return this chunk

    for r in context.results:
        print(f"{fmt(r.score)}  vec {fmt(r.vector_score)}  kw {fmt(r.keyword_score)}  {r.chunk.source:12} {r.chunk.text[:60]}…")
    """),
    md("""
    ## 7 · Hybrid weighting

    `hybrid_alpha` blends the two searches: `0` is keywords only, `1` is vectors only, `0.5` (the default)
    is both. Keywords win on exact terms like product names and codes.
    """),
    code("""
    for alpha in (0.0, 0.5, 1.0):
        hits = rag.search("which plan includes SSO", top_k=3, hybrid_alpha=alpha).results
        print(f"alpha={alpha}: {[h.chunk.source for h in hits]}")
    """),
    md("""
    ## 8 · Filters

    `IndexFilters` narrows the search to some sources, documents or metadata values before ranking.
    """),
    code("""
    from shipit_agent.rag import IndexFilters

    for f in (IndexFilters(sources=["kb/support.md"]), IndexFilters(metadata_match={"team": "billing"})):
        hits = rag.search("response time", top_k=3, filters=f).results
        print([h.chunk.source for h in hits])
    """),
    md("""
    ## 9 · Neighbouring chunks

    A hit can come back with the chunks around it (`chunks_above`, `chunks_below`), so the model sees the
    passage in context. Here the documents are split small to show it.
    """),
    code("""
    fine = RAG(vector_store=InMemoryVectorStore(), keyword_store=InMemoryBM25Store(),
               embedder=HashingEmbedder(dimension=256), chunker=DocumentChunker(target_tokens=24, overlap_tokens=0))
    fine.index_text(DOCS["security.md"], source="security.md")
    hit = fine.search("penetration test", top_k=1, chunks_above=1).results[0]
    print("expanded above:", len(hit.expanded_above))
    for c in hit.expanded_above:
        print("  above:", c.text[:70])
    print("  hit:  ", hit.chunk.text[:70])
    """),
    md("""
    ## 10 · Fetch a chunk by id

    Search results carry chunk ids; `fetch_chunk()` reads one back, optionally with its neighbours. The agent's
    `rag_fetch_chunk` tool uses this to read more around a hit.
    """),
    code("""
    first = rag.search("encryption", top_k=1).results[0].chunk
    again = rag.fetch_chunk(first.id)
    print(again.id == first.id, "|", again.source, "|", again.text[:80])
    """),
    md("""
    ## 11 · Search results as prompt context

    `to_prompt_context()` formats the results as numbered passages, ready to paste into a prompt when you call a
    model yourself.
    """),
    code("""
    print(rag.search("uptime SLA", top_k=2).to_prompt_context()[:600])
    """),
    md("""
    ## 12 · Real embeddings: Amazon Titan on Bedrock

    `CallableEmbedder` wraps any function that turns texts into vectors. Here, Titan Text Embeddings v2 through
    `boto3`. Real embeddings match *meaning*, not just words.
    """),
    code("""
    import json

    import boto3

    bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))

    def titan(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            body = json.dumps({"inputText": text, "dimensions": 256})
            response = bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=body)
            vectors.append(json.loads(response["body"].read())["embedding"])
        return vectors

    from shipit_agent.rag import CallableEmbedder

    semantic = RAG.default(embedder=CallableEmbedder(titan, dimension=256))
    for path in sorted(folder.glob("*.md")):
        semantic.index_file(str(path))
    print("indexed", semantic.count(), "chunks with Titan")
    """),
    md("""
    ## 13 · Words versus meaning

    The question below shares almost no words with the answer ("money back" vs "refund"). Vector-only search
    (`hybrid_alpha=1`) with each embedder, ranked by vector similarity. On four short documents both put the refund
    policy first, helped by shared words like "after"; Titan scores it twice as high, because it compares
    meaning. The gap matters as a corpus grows and wording drifts.
    """),
    code("""
    question = "can I get my money back if I stop using it after a few weeks?"
    for name, index in (("hashing", rag), ("titan", semantic)):
        hits = index.search(question, top_k=4, hybrid_alpha=1.0).results
        print(f"{name:8}", [f"{h.chunk.source.removeprefix('kb/')} {fmt(h.vector_score)}" for h in hits])
    """),
    md("""
    ## 14 · Reranking with a model

    A reranker reads the top candidates and reorders them by how well they answer the question. `LLMReranker`
    uses any model; pass it to `RAG.default(reranker=...)` and search with `enable_reranking=True`.
    """),
    code("""
    from shipit_agent.rag import LLMReranker

    reranked = RAG.default(embedder=CallableEmbedder(titan, dimension=256), reranker=LLMReranker(llm=haiku))
    for path in sorted(folder.glob("*.md")):
        reranked.index_file(str(path))

    q = "which plan gets help fastest when production is down?"
    for flag in (False, True):
        hits = reranked.search(q, top_k=3, enable_reranking=flag).results
        print("reranked" if flag else "original", [h.chunk.source for h in hits],
              [fmt(h.rerank_score) for h in hits] if flag else "")
    """),
    md("""
    ## 15 · Keeping the index current

    `reindex(document_id, content=...)` replaces a document's chunks; `delete_document()` removes them.
    """),
    code("""
    doc_id = rag.search("Starter costs", top_k=1).results[0].chunk.document_id
    rag.reindex(doc_id, content="# Plans and pricing\\nStarter now costs $15 per seat per month.")
    print(rag.search("Starter price per seat", top_k=1).results[0].chunk.text)

    before = rag.count()
    rag.delete_document(doc_id)
    print("chunks:", before, "->", rag.count())
    rag.index_file(str(folder / "plans.md"))
    """),
    md("""
    ## 16 · Give it to an agent

    `Agent(rag=rag)` adds three tools (`rag_search`, `rag_fetch_chunk`, `rag_list_sources`) and a prompt
    section telling the model to search before answering and to cite passages as `[1]`, `[2]`.
    """),
    code("""
    agent = Agent(llm=haiku, rag=semantic)
    print("tools:", [t.name for t in agent.tools])
    result = agent.run("If I cancel a monthly Team plan after 45 days, what do I get back, and how long does it take?")
    print(result.output)
    """),
    md("""
    ## 17 · The sources behind the answer

    `result.rag_sources` lists the passages the answer drew on, numbered the way the citations are.
    """),
    code("""
    for s in result.rag_sources:
        print(f"[{s.index}] {s.source:12} score {s.score:.3f}  {s.text[:70]}…")
    """),
    md("""
    ## 18 · Watch it search

    Streaming shows each search the agent makes and what came back.
    """),
    code("""
    for e in Agent(llm=haiku, rag=semantic).stream("Where is EU customer data stored, and how is it protected?"):
        if e.type == "tool_called":
            print("search:", e.payload["tool"], e.payload["arguments"])
        elif e.type == "tool_completed":
            print("  ->", e.payload["output"][:110].replace("\\n", " "), "…")
        elif e.type == "run_completed":
            print("\\n" + e.payload["output"])
    """),
    md("""
    ## 19 · An answer that isn't in the documents

    A good RAG agent says so instead of inventing one.
    """),
    code("""
    print(Agent(llm=haiku, rag=semantic).run("Do you offer a student discount?").output)
    """),
    md("""
    ## 20 · The same RAG on Gemma 4

    One index can serve many agents. Gemma 4 31B on Bedrock, same question as section 16:
    """),
    code("""
    result = Agent(llm=gemma, rag=semantic).run(
        "If I cancel a monthly Team plan after 45 days, what do I get back, and how long does it take?")
    print(result.output)
    print("sources:", [s.source for s in result.rag_sources])
    """),
    md("""
    ## 21 · RAG tools without the prompt

    To control the instructions yourself, attach the tools with `rag.as_tools()` and add `rag.prompt_section()`
    (or your own words) to the prompt.
    """),
    code("""
    custom = Agent(llm=haiku, tools=semantic.as_tools(),
                   prompt="Answer from the knowledge base in one sentence, then cite like [1].")
    print([t.name for t in custom.tools])
    print(custom.run("What does Enterprise add over Team?").output)
    """),
    md("""
    ## 22 · Clean up
    """),
    code("""
    import shutil

    shutil.rmtree(folder)
    """),
    md("""
    ## 23 · Summary

    - `RAG.default(embedder=...)` gives hybrid vector + BM25 search in memory; `index_text` / `index_file` fill it.
    - Tune with `top_k`, `hybrid_alpha`, `IndexFilters`, neighbouring chunks and a reranker.
    - `HashingEmbedder` is offline and word-based; wrap a real embedder with `CallableEmbedder` for meaning.
    - `Agent(rag=rag)` searches, cites as `[N]`, and returns the passages in `result.rag_sources`.
    - For persistent stores (Chroma, Qdrant, pgvector), see the RAG adapters page in the docs.

    **Next:** Guide 07 — sessions and memory.
    """),
]
