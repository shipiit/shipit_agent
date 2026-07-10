DOCUMENT_BUILDER_PROMPT = """
Create polished, ready-to-share documents: PDF reports, Excel workbooks,
Word documents, PowerPoint decks, and styled HTML.

Structure your content once and pick the output `kind`:

- pdf / docx / html — pass `title` + `sections` (heading, body, bullets,
  optional table). Rendering handles typography, spacing, and table styling.
- pptx — each section becomes a slide (heading = slide title, bullets =
  slide body). A title slide is added automatically.
- xlsx — pass `sheets` (name, headers, rows). Header styling, frozen
  panes, and column sizing are applied automatically; cell values that
  start with "=" are written as live formulas.

Guidelines:
- Prefer tables for numbers, bullets for takeaways, short paragraphs for
  narrative. Don't dump raw text into one section.
- Give files meaningful names; the tool returns the saved path.
- If the needed library is missing the tool says which `pip install`
  fixes it — relay that instead of retrying.
""".strip()
