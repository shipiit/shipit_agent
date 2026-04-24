from __future__ import annotations

DASHBOARD_RENDER_PROMPT = """
## render_dashboard
Render a structured life/finance/research dashboard as a single self-contained HTML artifact.

**When to use:**
- User asks for a "visual dashboard", "one-pager", "life vision", "future timeline",
  "finance breakdown", or any other request that wants chart + card layouts rather
  than bullet points.
- The answer has natural sections (metrics, a growth chart, a timeline of events,
  comparison cards, phase-by-phase plan, a final verdict) that benefit from
  distinct visual treatment.
- After a long analysis, a compact dashboard summarises findings for a
  stakeholder who won't read prose.

**How to use:**
- Build a spec dict with:
  - ``title``, optional ``subtitle``, optional ``lang`` (``"en"``, ``"hi"``, ...).
  - ``sections``: list of typed blocks. Supported ``type`` values:
    - ``metrics``            — KPI tiles (``columns`` 2/3/4, each with ``label`` / ``value`` / ``sub``).
    - ``line_chart`` / ``bar_chart`` — labels + numeric values; renders Chart.js.
    - ``bars``               — horizontal percentage bars for ranked factors.
    - ``timeline``           — dated events with optional badge tags.
    - ``cards``              — side-by-side trait cards (2 or 3 columns).
    - ``lifestyle_grid``     — 3-column icon tiles.
    - ``phases``             — vertical phase stack with colored left border.
    - ``callout``            — single highlight box.
    - ``verdict``            — green summary box; supports ``**bold**`` inline.
- Set ``export=true`` and a ``path`` to also write the HTML to disk.
- Pair with ``artifact_builder`` only when the caller wants raw text — for HTML
  this tool already returns an artifact and Autopilot will collect it.

**Rules:**
- Keep each section short — 4–8 items is a good upper bound. A 30-row timeline
  reads worse than a 6-row one, not better.
- Prefer hex color strings (``#1d9e75``) for accents; badge variants are
  ``blue`` / ``green`` / ``amber`` / ``purple`` / ``gray`` / ``red``.
- Numbers in ``metrics.value`` should be concise — "3-5x", "MRR", "$12k" read
  better than a full sentence.
- Use ``verdict`` for the closing paragraph, not for body copy.
""".strip()
