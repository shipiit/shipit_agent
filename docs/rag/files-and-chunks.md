# Files, Chunks, and Sources — A Cookbook

This page is the practical "how do I…" companion to the rest of the
Super RAG docs. It covers four real-world tasks:

1. **Index a big PDF or Markdown file**
2. **Persist the resulting chunks to disk** (the "chunk file")
3. **Reload chunks later and feed them into an `Agent`**
4. **Understand what `source` means in RAG**

Everything below runs on the stdlib-only defaults — no extra dependencies
unless you want PDF support.

---

## 1. Index a big PDF or Markdown file

### Markdown

Markdown works out of the box, no extras required:

```python
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
chunks = rag.index_file("docs/big_manual.md")

print(f"Indexed {len(chunks)} chunks from the manual")
print(f"Total chunks in store: {rag.count()}")
```

### PDF

PDF needs `pypdf` (lazy-imported only when you actually open a PDF):

```bash
pip install shipit-agent[rag-pdf]
```

Then it's the same call:

```python
rag = RAG.default(embedder=HashingEmbedder(dimension=512))
chunks = rag.index_file("docs/big_manual.pdf")

print(f"Indexed {len(chunks)} chunks")
```

### Tuning chunk size for big documents

The default chunker targets ~512 tokens with 64-token overlap. For a
very large document, you might want bigger chunks (fewer of them, more
context per hit) or smaller chunks (finer-grained retrieval):

```python
from shipit_agent.rag import DocumentChunker

big_chunks = RAG(
    vector_store=...,
    embedder=HashingEmbedder(dimension=512),
    chunker=DocumentChunker(target_tokens=1024, overlap_tokens=128),
)
big_chunks.index_file("docs/big_manual.pdf")
```

For huge PDFs (hundreds of pages) it is usually safe to crank
`target_tokens` to 1024–2048 — your retrieval becomes coarser but the
LLM gets more context per hit.

### Indexing many files at once

```python
import pathlib

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
for path in pathlib.Path("docs").rglob("*.md"):
    rag.index_file(str(path))

for path in pathlib.Path("docs").rglob("*.pdf"):
    rag.index_file(str(path))

print(f"Total: {rag.count()} chunks across {len(rag.list_sources())} files")
```

`index_file` derives a stable `document_id` from the file path, so
re-running this loop on an already-indexed file *replaces* the old
chunks instead of duplicating them.

---

## 2. Persist the chunk file (save chunks to disk)

The default `InMemoryVectorStore` lives in RAM. For anything you want
to keep, save the chunks to a file. The chunks are plain dataclasses,
so JSON is the easiest format:

```python
import json
from dataclasses import asdict
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/big_manual.pdf")

# Grab every chunk in the store
all_chunks = rag.vector_store.all_chunks()

# Serialize to a chunk file
def chunk_to_json(c):
    d = asdict(c)
    # Embeddings are float lists already; created_at is the only special case.
    if d.get("created_at"):
        d["created_at"] = c.created_at.isoformat()
    return d

with open("manual_chunks.json", "w") as f:
    json.dump([chunk_to_json(c) for c in all_chunks], f)

print(f"Saved {len(all_chunks)} chunks to manual_chunks.json")
```

`asdict` writes everything you need: `id`, `document_id`, `chunk_index`,
`text`, `text_for_embedding`, `metadata`, `source`, `start_char`,
`end_char`, **and the precomputed `embedding`**. The chunk file is fully
self-contained — you don't need to re-run the embedder when reloading.

> **Tip** — for very large corpora write one chunk per line (JSONL)
> instead of a single big JSON array, so you can stream-load later
> without holding the whole file in memory.

---

## 3. Reload the chunk file and use it with an Agent

To rehydrate, build the dataclasses back, drop them into an
`InMemoryVectorStore`, wire it into a `RAG`, and pass `rag=` to your
`Agent`:

```python
import json
from datetime import datetime
from shipit_agent import Agent
from shipit_agent.rag import (
    RAG,
    Chunk,
    HashingEmbedder,
    InMemoryBM25Store,
    InMemoryVectorStore,
)

# 1. Read the chunk file
with open("manual_chunks.json") as f:
    raw = json.load(f)

# 2. Rebuild Chunk dataclasses
chunks = []
for d in raw:
    if d.get("created_at"):
        d["created_at"] = datetime.fromisoformat(d["created_at"])
    chunks.append(Chunk(**d))

# 3. Hydrate stores — embeddings are already on the chunks, so we tell
#    RAG not to re-embed on add.
vector_store = InMemoryVectorStore()
keyword_store = InMemoryBM25Store()
vector_store.add(chunks)
keyword_store.add(chunks)

rag = RAG(
    vector_store=vector_store,
    keyword_store=keyword_store,
    embedder=HashingEmbedder(dimension=512),  # must match the original
    auto_embed_on_add=False,                  # prevents re-embedding
)

# 4. Plug into any agent
agent = Agent(llm=my_llm, rag=rag)

result = agent.run("Summarise the manual's installation chapter")
print(result.output)

# Citations come back automatically
for src in result.rag_sources:
    print(f"[{src.index}] {src.source} (chunk {src.chunk_id})")
    print(f"    {src.text[:120]}")
```

The same pattern works for **deep agents** — pass `rag=` to
`GoalAgent`, `Supervisor`, etc., and every step of the workflow can
hit your reloaded chunks.

```python
from shipit_agent.deep import Goal, GoalAgent

goal_agent = GoalAgent(
    llm=my_llm,
    goal=Goal(
        objective="Write release notes for the manual update",
        success_criteria=["Mentions installation changes", "Mentions API changes"],
    ),
    rag=rag,
)
result = goal_agent.run()
```

### Skipping the chunker — feed chunks directly

If you've already chunked the document yourself (or the chunks came
from another tool), you can skip the chunker entirely. Build `Chunk`
objects, embed them, drop them into the store:

```python
from shipit_agent.rag import Chunk, HashingEmbedder, InMemoryVectorStore

embedder = HashingEmbedder(dimension=512)
my_chunks = [
    Chunk(id="manual::0", document_id="manual", chunk_index=0, text="Install with pip."),
    Chunk(id="manual::1", document_id="manual", chunk_index=1, text="Configure via .env."),
    Chunk(id="manual::2", document_id="manual", chunk_index=2, text="Run with `shipit run`."),
]
for c in my_chunks:
    c.embedding = embedder.embed([c.text_for_embedding])[0]

store = InMemoryVectorStore()
store.add(my_chunks)
rag = RAG(vector_store=store, embedder=embedder, auto_embed_on_add=False)
```

### Passing only specific chunk IDs to the agent

Sometimes you don't want the LLM to retrieve freely — you've already
picked the relevant chunks (maybe via your own ranking) and just want
the agent to read them. Use `rag.fetch_chunk(chunk_id)` and inline the
text into the user prompt:

```python
chunk_a = rag.fetch_chunk("manual::12")
chunk_b = rag.fetch_chunk("manual::13")

context = f"""Reference passages:

[1] {chunk_a.text}
[2] {chunk_b.text}
"""

result = agent.run(f"{context}\n\nQuestion: How do I configure logging?")
```

Or, for the agent-driven path, pre-record the chunks as sources before
the run so they show up in `result.rag_sources`:

```python
rag.begin_run()
for cid in ["manual::12", "manual::13"]:
    rag.fetch_chunk(cid)            # records into the source tracker
result = agent.run("How do I configure logging? Use the prior context.")
print(result.rag_sources)
```

---

## 4. What is `source` in RAG?

`source` is a **human-readable label** that identifies where a chunk
came from. It is metadata, not identity — many chunks can share the
same source.

| Concept | Identifier | Example |
| --- | --- | --- |
| `document_id` | Stable internal id | `manual` (auto-generated from path) |
| `chunk_id` | Per-chunk id | `manual::0`, `manual::1`, … |
| `source` | Human label | `"docs/big_manual.pdf"`, `"readme.md"`, `"slack#general"` |

### Where `source` comes from

| How you index | What `source` becomes |
| --- | --- |
| `index_file("docs/big_manual.pdf")` | the file path → `"docs/big_manual.pdf"` |
| `index_text("...", source="readme.md")` | whatever you pass |
| `index_text("...")` (no source) | `None` |
| `index_document(Document(source="slack#general"))` | whatever you set |

### Why `source` matters

1. **Citations.** When the agent answers, every entry in
   `result.rag_sources` carries `src.source` — that's what you
   render next to the `[N]` marker in your UI:

   ```text
   "Shipit supports Python 3.10+. [1]"

   [1] readme.md (chunk readme::0, score 0.87)
   ```

2. **Filtering.** You can scope a search to specific sources:

   ```python
   from shipit_agent.rag import IndexFilters
   ctx = rag.search("python", top_k=3,
                    filters=IndexFilters(sources=["readme.md", "install.md"]))
   ```

3. **`rag_list_sources` tool.** Lets the LLM ask "what do you have
   indexed?" — and the answer is exactly the unique `source` values:

   ```python
   rag.list_sources()
   # ['docs/big_manual.pdf', 'readme.md', 'slack#general']
   ```

4. **Grouping in your UI.** Group `rag_sources` by `source` to render
   per-document citation panels.

### `source` vs `document_id` vs `chunk_id` — which do I use when?

- **Want to *cite*?** → use `source` (or `chunk_id` for an exact
  pointer).
- **Want to *re-index* a document?** → use `document_id` so old chunks
  get replaced. Pass it explicitly when you call `index_text`:
  ```python
  rag.index_text("v2 content", document_id="manual", source="manual.md")
  ```
- **Want to *fetch a specific chunk*?** → use `chunk_id` with
  `rag.fetch_chunk(chunk_id)` or the `rag_fetch_chunk` agent tool.
- **Want to *delete one document*?** → use `document_id` with
  `rag.delete_document(document_id)`.

### Custom source labels

`source` is a free-form string — use whatever makes sense to your
users. A few ideas:

```python
rag.index_text(slack_msg.text, source=f"slack#{channel}")
rag.index_text(jira_issue.body, source=f"jira:{issue.key}")
rag.index_text(meeting_transcript, source=f"zoom:{meeting_id}")
rag.index_text(email.body, source=f"gmail:{email.thread_id}")
```

When the agent later cites these, your UI can render them as clickable
links back to the original system — that's the entire DRK_CACHE-style
experience, free of charge.

---

## See also

- [Standalone RAG](standalone.md) — full indexing/search reference
- [RAG + Agent](with-agent.md) — wiring `rag=` into an Agent
- [API reference](api.md) — every dataclass field and method
- Notebook: `notebooks/22_rag_basics.ipynb`
