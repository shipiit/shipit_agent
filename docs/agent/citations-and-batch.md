---
title: Citations & Batch API
description: Attach source documents with citations enabled and parse Anthropic's citations back out of metadata for verifiable RAG. Plus the Batch API runtime — BatchRequest / BatchResult / BatchRuntime.run() — for ~50%-cheaper bulk runs.
---

# Citations & Batch API

Shipit_agent ships two Anthropic API passthroughs for
production-grade workloads: **document citations** (verifiable, grounded
answers) and a **Batch API runtime** (bulk runs at roughly half price).

## Citations — verifiable RAG

When you attach a source `document` block with `citations.enabled`, the model
**grounds its answer in that document** and emits `citations` on the text blocks
of its reply — each pointing back at a character, page, or content-block range
in the source. shipit parses those into `LLMResponse.metadata["citations"]`, so
every claim is traceable back to its source span. That's the difference between
RAG that *says* it used a source and RAG you can **verify**.

### Document helpers

The constructors live in `shipit_agent.llms` (from
`shipit_agent.llms.citations`). Each builds a `document` content block in the
SDK's source-param shape; **citations are enabled by default** — that is the
whole point of the helper:

| Helper | Source type | Use for |
| --- | --- | --- |
| `text_document(text, *, title=None, context=None, citations=True)` | `text` | Plain-text sources. |
| `pdf_document(data_base64, *, title=None, context=None, citations=True)` | `base64` | A base64-encoded PDF. |
| `url_pdf_document(url, *, title=None, context=None, citations=True)` | `url` | A PDF fetched from a URL. |
| `content_document(content, *, title=None, context=None, citations=True)` | `content` | A document assembled from content blocks. |

```python
from shipit_agent.llms import AnthropicChatLLM, text_document, url_pdf_document

# Attach default documents to every call on this adapter…
llm = AnthropicChatLLM(
    model="claude-sonnet-5-5",
    documents=[
        text_document("Refunds are processed within 5 business days.",
                      title="Refund policy"),
        url_pdf_document("https://example.com/handbook.pdf", title="Handbook"),
    ],
)

response = llm.complete(messages=[...])   # or pass documents=[...] per call
print(response.content)

for cite in response.metadata.get("citations", []):
    print(cite)   # e.g. {"type": "char_location", "document_title": ..., ...}
```

Documents passed to `AnthropicChatLLM(documents=[...])` are attached to **every**
`complete()` call; a per-call `documents=[...]` argument overrides them. The
blocks are prepended to the last user message.

### Parsing citations back out

`extract_citations(content_blocks)` walks the response's text blocks, reads each
block's `citations` (location objects like `char_location`, `page_location`,
`content_block_location`), and returns them as plain dicts — which the adapter
places at `metadata["citations"]` (only present when the response actually cited
something). It's defensive throughout: any block shape that doesn't look like a
cited text block is skipped, so non-citation responses simply yield `[]`.

### Provider note

Citations are an **Anthropic** feature. They work with `AnthropicChatLLM` (and
Anthropic models reached via Bedrock / LiteLLM). Other providers ground answers
through their own mechanisms; the document-citation shape here is Anthropic's.

## Batch API — ~50%-cheaper bulk runs

For large, latency-tolerant workloads — evals, backfills, nightly
summarisation, dataset labelling — the **Anthropic Messages Batches API**
processes many requests asynchronously and is billed at roughly **50% of the
standard per-token price**. shipit wraps it in
`shipit_agent.batch.BatchRuntime`.

```python
from shipit_agent.batch import BatchRequest, BatchRuntime

runtime = BatchRuntime(api_key="sk-...")

results = runtime.run([
    BatchRequest(custom_id="q1", prompt="Summarise this ticket: ..."),
    BatchRequest(custom_id="q2", prompt="Classify sentiment: ..."),
])

for r in results:
    if r.ok:
        print(r.custom_id, r.output)
    else:
        print(r.custom_id, "ERROR:", r.error)
```

### `BatchRequest`

One request to include in a batch:

| Field | Meaning |
| --- | --- |
| `custom_id` | Caller-provided id, echoed back on the matching `BatchResult`. Unique within a batch. |
| `prompt` | Convenience single-turn user prompt (used to build `messages` when `messages` is not set). |
| `messages` | Explicit `[{"role", "content"}]` list; takes precedence over `prompt`. |
| `system` | Optional system prompt (omitted from the payload when `None`). |
| `max_tokens` | Max output tokens for this request (default `1024`). |
| `model` | Model id for this request (default `claude-opus-5-5`). |
| `metadata` | Optional `metadata` object forwarded to the API. |

### `BatchResult`

The outcome of a single batched request:

| Field | Meaning |
| --- | --- |
| `custom_id` | The originating request's id. |
| `output` | Concatenated assistant text on success, otherwise `""`. |
| `usage` | The message `usage` object on success, otherwise `None`. |
| `error` | Human-readable error for `errored` / `canceled` / `expired` results, otherwise `None`. |
| `result_type` | Raw discriminator: `succeeded` / `errored` / `canceled` / `expired`. |
| `raw` | The underlying SDK result object (stop reason, content blocks, request id, …). |
| `.ok` | `True` only when the request `succeeded` with no error captured. |

### `BatchRuntime`

`BatchRuntime.run(requests, *, poll_interval=30.0, timeout=86400, ...)` is the
one-call path: it **submits**, **polls** until the batch ends, and returns mapped
`BatchResult`s. The lower-level operations are also exposed:

- `submit(requests) -> batch_id` — create the batch.
- `status(batch_id) -> str` — `"in_progress"`, `"canceling"`, or `"ended"`
  (only `"ended"` is terminal).
- `results(batch_id) -> list[BatchResult]` — stream and map the results.
- `cancel(batch_id) -> str` — request cancellation; returns the new status.

`run()` raises `TimeoutError` if the batch doesn't reach `"ended"` within
`timeout` (default 24h). Per-entry mapping is wrapped so a malformed entry
becomes a `BatchResult` with `error` set rather than raising. Pass a pre-built
`client=` (or any object exposing `messages.batches.create/retrieve/results/
cancel`) for testing; `sleep=` and `now=` on `run()` are injectable for
deterministic tests. `MessageBatchRunner` is an alias for `BatchRuntime`.

### Provider note

Both features are **Anthropic** today — citations use Anthropic's document
blocks, and the batch runtime wraps Anthropic's Messages Batches API. OpenAI
also has a Batch API; **generalising the batch runtime across providers is on
the roadmap**.

## See also

- [Server-side tools](./server-side-tools.md) — Anthropic-hosted
  `web_search` / `code_execution` / `bash` / `text_editor` / `computer_use`.
- [Interleaved thinking & context editing](./interleaved-thinking.md) — the
  third Anthropic API passthrough.
- [With RAG](./with-rag.md) — the built-in retrieval pipeline that pairs with
  citation-grounded answers.
- [Cost tracking](../guides/cost-tracking.md) — track spend across normal and
  batched runs.
