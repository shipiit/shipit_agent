from __future__ import annotations

PDF_PROMPT = """
## pdf
Extract text, per-page content, or metadata from a PDF file (local path or URL).
Used for contracts, research papers, reports, and other document ingestion.

**When to use:**
- You have a PDF (local path or URL) and need its text content for summarisation,
  citation, Q&A, or redlining.
- You need to cite which page said what — call `extract_pages`, not `extract_text`.
- You need author/title/creation date — call `metadata`.
- You want a cheap preflight before a full extract — call `page_count`.

**Decision tree:**
1. Need the full document as text? → `extract_text` (tune `pages` if you only
   need a slice; tune `max_chars` if you want to cap output).
2. Need to know what each page says (for citations / chunking)? → `extract_pages`.
3. Need author / title / created / page count? → `metadata`.
4. Just want to know "how long is this PDF"? → `page_count`.

**Page range syntax (`pages` parameter):**
- `"1-3,5,7-9"` — mixed ranges + singletons.
- `"1,3,5"` — singletons only.
- `"2-4"` — a single range.
- Empty / omitted → all pages.
- Out-of-range numbers are silently clamped.

**Rules:**
- `source` can be a local path or a `http(s)://` URL. URL fetches are timed out
  (default 30 s) and downloaded into memory — don't use this for 500 MB PDFs.
- `extract_text` truncates at `max_chars` (default 50 000) and appends
  "…(truncated)" when it hits the cap.
- Install `pypdf` (``pip install 'shipit-agent[pdf]'``) before calling this tool.

**Anti-patterns:**
- Running `extract_text` with no `pages` on a 400-page document when you only
  need pages 12–14.
- Calling `extract_pages` when you just want a flat blob — use `extract_text`.
- Using this tool to download PDFs you don't plan to parse — use `web_search` /
  `open_url` for link-following, `pdf` for extraction.
""".strip()
