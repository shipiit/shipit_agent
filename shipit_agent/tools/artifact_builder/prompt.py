"""What the model is told about the artifact builder tool: when to use it and how."""

from __future__ import annotations

ARTIFACT_BUILDER_PROMPT = """

## build_artifact
Create a deliverable the user will keep, share or reuse — a report, a web
page, a code file, a diagram, a data file — and keep improving the same one.

**When to use:**
- The answer is a document or file, not a chat reply: reports, specs, plans,
  HTML pages, scripts, SVG or Mermaid diagrams, JSON or CSV data
- The user asks you to change something you already produced

**How:**
- `action="create"` with a short stable `id` (like `q3-report`), a `title`,
  a `type` (markdown, html, code, svg, mermaid, json, csv, text; add
  `language` for code) and the full `content`.
- To change it, reuse the same `id`:
  - `action="update"` with `old_text` (exact, unique) and `new_text` for a
    targeted edit;
  - `action="rewrite"` with new `content` when most of it changes.
- Every change is saved as a new version; earlier ones are kept.

**Rules:**
- One id per deliverable. Do not create `report-v2`; update `report`.
- Put the complete deliverable in the artifact; in chat, say what it is and
  what changed, without pasting it again.
""".strip()
