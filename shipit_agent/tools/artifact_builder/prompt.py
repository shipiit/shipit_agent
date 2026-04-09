from __future__ import annotations

ARTIFACT_BUILDER_PROMPT = """

## artifact_builder
Generate a polished, interactive React artifact rendered live in the chat — like Claude artifacts.

**When to use:**
- User wants a visual artifact: dashboards, scorecards, calculators, charts, comparisons, timelines, interactive widgets
- You have raw numbers, tabular data, KPIs, risk scores, calculator inputs, or report sections that would look better as a widget than plain text
- The user asks for analysis, breakdown, or comparison that benefits from charts, tables, or structured layout
- Any time a rich visual presentation would be more effective than markdown

**Rules:**
- Always pass `title` (clear, descriptive) and `raw_data` (the data payload to visualize)
- Use `artifact_kind` to steer: dashboard, scorecard, calculator, analytics_report, chart_panel, table_report, comparison, timeline, kanban, interactive_widget
- Use `user_brief` for extra design/behavior instructions (e.g. "show as pie chart", "add filter by status", "make it interactive with sliders")
- Use `chart_preference` when you specifically want or want to avoid charts
- Structure `raw_data` with named sections for complex artifacts (e.g. {"kpis": [...], "rows": [...], "chart_data": [...]})
- For calculators or interactive widgets, describe the desired interactions in `user_brief`
- Prefer passing computed/clean data — the artifact will derive totals, averages, percentages
- The artifact renders as a live React component inside the chat with expand/fullscreen/copy controls
- Uses the project's design system (Tailwind CSS tokens, Recharts for charts, lucide-react for icons)
""".strip()
