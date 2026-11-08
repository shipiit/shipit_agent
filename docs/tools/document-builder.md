---
title: Document Builder
description: build_document — polished PDF reports, Excel workbooks with live formulas, Word documents, PowerPoint decks, and styled HTML from one structured payload.
---

# Document Builder — `build_document`

**** The agent's deliverable engine: structure content once,
pick an output `kind`, and get a finished, shareable file — not a text dump.
Attached automatically by `Agent.with_builtins`, `Agent.for_role`, and
`Agent.for_project`.

| Kind | Output | Renderer (optional dep) |
| --- | --- | --- |
| `pdf` | Styled report — accent headings, zebra-striped tables | `reportlab` |
| `xlsx` | Workbook — bold frozen header row, auto-sized columns, **live `=` formulas** | `openpyxl` |
| `docx` | Word document — headings, bullets, styled tables | `python-docx` |
| `pptx` | Deck — title slide + one slide per section | `python-pptx` |
| `html` | Self-contained styled page (print-to-PDF fallback) | none |

Missing a renderer? The tool replies with the exact `pip install` fix instead
of failing cryptically.

## Content model

For `pdf` / `docx` / `pptx` / `html`, pass `title` + `sections` — each section
takes a `heading`, `body`, `bullets`, and/or a `table`:

```json
{
  "kind": "pdf",
  "title": "Q2 Report",
  "sections": [
    {
      "heading": "Highlights",
      "body": "Revenue grew 24% quarter over quarter.",
      "bullets": ["ARR up 24%", "Churn down to 1.1%"],
      "table": {
        "headers": ["Metric", "Q1", "Q2"],
        "rows": [["Revenue", 100, 124], ["Churn %", 1.4, 1.1]]
      }
    }
  ]
}
```

For `xlsx`, pass `sheets` — cell strings starting with `=` are written as
**live formulas**:

```json
{
  "kind": "xlsx",
  "title": "Q2 Close",
  "sheets": [
    {
      "name": "P&L",
      "headers": ["Item", "Amount"],
      "rows": [["Revenue", 124000], ["Costs", -78500], ["Net", "=B2+B3"]]
    }
  ]
}
```

## In practice

You rarely call it directly — you ask the agent for a deliverable:

```python
from shipit_agent import Agent

agent = Agent.for_role("finance-analyst", llm=llm)
result = agent.run(
    "Build the Q2 close: a P&L workbook with a net-income formula, "
    "and a 5-slide summary deck for the board."
)
# → .shipit_workspace/documents/q2_close.xlsx
# → .shipit_workspace/documents/q2_board_deck.pptx
```

The tool result includes the saved path and byte size in `metadata`
(`path`, `bytes`, `kind`, `ok`). Files land under
`.shipit_workspace/documents/` unless you pass an explicit `path` — the
correct suffix for the chosen `kind` is enforced either way.

## Direct usage

```python
from shipit_agent.tools import DocumentBuilderTool
from shipit_agent.tools.base import ToolContext

tool = DocumentBuilderTool(workspace_root="out/docs")
out = tool.run(
    ToolContext(prompt="", system_prompt="", state={}),
    kind="html",
    title="Release Notes",
    sections=[{"heading": "v1.0.15", "bullets": ["Sector roles", "MCP catalog"]}],
)
print(out.metadata["path"])
```

## Related

- [The super agent](../agent/index.md)
- [Dashboard render](dashboard-render.md)
- [Tool catalog](index.md)
