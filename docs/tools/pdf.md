---
title: pdf
description: Extract text, per-page content, or metadata from a PDF (local path or URL). Lazy pypdf import, page-range syntax, char budget for extract_text.
---

# `pdf`

Pull structured text out of PDFs — contracts, research papers,
reports, invoices — without shelling out to an external service.
Works on local paths and `http(s)://` URLs; the URL branch fetches
into memory with a 30 s default timeout. `pypdf` is imported lazily,
so the base install stays slim and the tool reports
`pypdf_missing` if the extra wasn't installed.

> **TL;DR** —
> `PDFTool().run(ctx, action="extract_text", source="./contract.pdf", pages="1-5")`
> returns up to 50 000 characters of joined page text in
> `output.text` with `metadata.truncated` set when the cap was hit.

## When to use

- **Contract / legal review** — `extract_text` on a range of pages,
  then feed the result into a summariser.
- **Research / Q&A with citations** — `extract_pages` keeps each
  page's text addressable by page number.
- **Invoice / receipt ingestion** — `metadata` for title / author /
  dates, `extract_pages` for line items.
- **Cheap preflight** before committing tokens to a 400-page PDF —
  `page_count` answers "how long is this?" in one call.

## Setup

`PDFTool` is **not** a connector — no credentials. The only
prerequisite is `pypdf`, which is gated behind an extra:

```bash
pip install 'shipit-agent[pdf]'        # installs pypdf
```

```python
from shipit_agent.tools.pdf import PDFTool

pdf = PDFTool(
    max_chars_default=50_000,   # cap for extract_text
    timeout_seconds=30,         # URL fetch timeout
)
```

If you call `pdf.run()` before installing the extra, the tool returns
a `pypdf_missing` error with the install hint — it never imports the
dependency at module load time.

## Quick example

```python
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.pdf import PDFTool

pdf = PDFTool()
ctx = ToolContext(prompt="demo")

# Extract the first 5 pages, capped at 10k chars
out = pdf.run(ctx,
              action="extract_text",
              source="./paper.pdf",
              pages="1-5",
              max_chars=10_000)
print(out.text[:500])
print(out.metadata["truncated"], out.metadata["char_count"])
```

## Page range syntax (`pages` parameter)

```text
  "1-3,5,7-9"      → pages 1, 2, 3, 5, 7, 8, 9
  "1,3,5"          → pages 1, 3, 5
  "2-4"            → pages 2, 3, 4
  ""   or omitted  → all pages
```

Out-of-range pages are silently dropped once `pypdf` has reported the
true page count. Inverted ranges (`"9-5"`) are auto-swapped.
Whitespace is tolerated around numbers and commas.

## As a tool handed to an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.tools.pdf import PDFTool

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-5.5"),
    tools=[PDFTool()],
    prompt=(
        "You are a contract reviewer. Use the pdf tool to extract the "
        "relevant pages, then summarise obligations, termination "
        "clauses, and payment terms."
    ),
)
agent.run("Summarise the termination clauses in ./nda.pdf (pages 3-7).")
```

## Actions

Four actions live on a single `action` enum.

### `extract_text`

Required: `source`. Optional: `pages` (page range spec), `max_chars`
(defaults to `PDFTool.max_chars_default`, i.e. 50 000).

Returns joined text (`"\n\n"` between pages) in `output.text`.
Truncation appends `"\n…(truncated)"` and sets
`metadata.truncated = True`. Set `max_chars=0` to disable the cap.

```python
pdf.run(ctx, action="extract_text",
        source="https://example.com/whitepaper.pdf",
        pages="1-10", max_chars=20_000)
```

### `extract_pages`

Required: `source`. Optional: `pages`. Returns a structured
`metadata.pages` list of `{"page": <1-indexed>, "text": "..."}` dicts
— use this when citations need to point at a specific page number.
Per-page extraction errors don't fail the action; the failing page
gets an `"error"` key in its entry and an empty `"text"`.

### `metadata`

Required: `source`. Returns title / author / subject / creator /
producer / creation_date / modification_date / page_count. Keys are
null when the PDF doesn't set them. The tool reads both raw PDF
keys (`"/Title"`) and their attribute aliases.

```python
pdf.run(ctx, action="metadata", source="./report.pdf")
```

### `page_count`

Required: `source`. Cheapest possible action — parses the PDF and
returns `"N pages."` plus `metadata.page_count`.

## `source` resolution

- **`http://...` / `https://...`** — fetched via `urllib.request`
  with `timeout_seconds` (default 30) and `OSError` / `URLError` /
  `TimeoutError` surfaced as `url_fetch_failed`.
- **Local path** — `~` is expanded; the path must exist and be a
  regular file.
- Anything else is rejected as `file_not_found`.

Downloads happen **into memory** — don't use this tool to process a
500 MB PDF; route those through an object-store pipeline instead.

## Error shapes

| `error=` | Meaning | What to do |
| --- | --- | --- |
| `unknown_action` | `action=` not in the enum | Use `extract_text` / `extract_pages` / `metadata` / `page_count`. |
| `missing_source` | `source=` was empty | Provide a path or URL. |
| `pypdf_missing` | `pypdf` isn't installed | `pip install 'shipit-agent[pdf]'`. |
| `url_fetch_failed` | HTTP / URL / timeout error fetching a remote PDF | `metadata.message` has the underlying error. |
| `file_not_found` | Local path didn't exist or wasn't a file | Check the path. |
| `file_read_failed` | `OSError` reading local bytes | Permissions / disk issue. |
| `pdf_parse_error` | `pypdf.PdfReader(stream)` raised | The file is corrupt or not actually a PDF. `metadata.message` has the underlying error. |

## Related

- [Tool catalog](index.md) — every built-in tool.
- [`vision`](vision.md) — for PDFs that are scanned images rather
  than text; render pages as images and route through vision.
- [`open_url`](core-tools.md#open_url) — for fetching HTML; `pdf` is
  the right tool only when you want parsed PDF text.
- [Specialists](../autopilot/specialists.md) — researcher / legal
  review roles that chain PDF extraction with summarisation.
