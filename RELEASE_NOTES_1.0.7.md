# SHIPIT Agent 1.0.7 — Agents for every role

**Release date — 2026-04-24**

Twelve new tools, nine new persona specialists, seven persona walk-through
notebooks. shipit-agent is no longer only a developer-agent framework — it
ships agents for developers, designers, sales reps, PMs, data analysts,
finance, customer support, and recruiters.

**1190 unit tests. 286 new in this release. Zero regressions.**

---

## What's new

### Core tools — everyone benefits

| Tool | Unlocks |
| --- | --- |
| `GitHubTool` | PRs, issues, reviews, workflows. github.com + GitHub Enterprise. Rate-limit aware. |
| `GitLabTool` | MRs, issues, pipelines. self-hosted + gitlab.com. |
| `SQLTool` | One tool, any SQLAlchemy dialect (Postgres, MySQL, BigQuery, Snowflake, MSSQL, …). Read-safe by default. |
| `VisionTool` | Image → text via any vision-capable LLM. File paths, URLs, data-URLs, base64. |
| `PDFTool` | Text, per-page content, metadata. Local paths + URL fetch. |
| `LangSmithExporter` + `OpenTelemetryExporter` | Ship every agent's trace to LangSmith or any OTLP backend (Datadog, Grafana, Honeycomb). |

### Persona SaaS connectors

| Tool | For |
| --- | --- |
| `FigmaTool` | Designers — read designs, comments, component libraries; post review comments. |
| `SalesforceTool` | Sales / CS — SOQL/SOSL queries, read accounts/opps/contacts, log activities safely. |
| `StripeTool` | Sales / Finance / Ops — read customers/charges/subs/invoices. Mutations gated. |
| `GoogleSheetsTool` | PM / Manager / Analyst — read/write cells, ranges, formulas, sheet structure. |
| `ZendeskTool` | Support — triage, search, comment; create/close gated for safety. |
| `LinkedInSearchTool` | Sales / Recruiter — **strictly read-only** lookup + search. No automation. |

### Nine new specialists in `agents.json`

`code-reviewer-bot` · `release-engineer` · `figma-designer` · `sales-rep` ·
`account-executive` · `sales-ops` · `recruiter` · `finance-analyst` ·
`customer-support-agent`.

Total specialists in the registry: **56**.

### Seven persona walk-through notebooks

Every notebook runs with `SimpleEchoLLM` and stubbed API calls — zero
credentials needed to see the flow:

- `47_pm_pr_digest.ipynb`
- `48_designer_figma_review.ipynb`
- `49_sales_lead_enrichment.ipynb`
- `50_manager_sheets_kpis.ipynb`
- `51_support_zendesk_triage.ipynb`
- `52_analyst_sql_to_dashboard.ipynb` (uses a real in-memory SQLite)
- `53_finance_stripe_pdf_cashflow.ipynb`

---

## Under the hood

**Test coverage — 286 new tests.**

| Test file | Tests |
| --- | --- |
| `test_github_tool.py` | 29 |
| `test_gitlab_tool.py` | 26 |
| `test_vision_tool.py` | 21 |
| `test_sql_tool.py` | 46 |
| `test_pdf_tool.py` | 23 |
| `test_tracing_exporters.py` | 15 |
| `test_figma_tool.py` | 17 |
| `test_salesforce_tool.py` | 22 |
| `test_stripe_tool.py` | 24 |
| `test_google_sheets_tool.py` | 21 |
| `test_zendesk_tool.py` | 23 |
| `test_linkedin_tool.py` | 19 |

Every connector ships with the same safety rails:
- `_request_or_error` wrapper — all HTTP errors surfaced as structured
  `ToolOutput` metadata, never raised.
- Rate-limit detection — 429 + `Retry-After` → `error="rate_limited"` +
  `retry_after_seconds`.
- Not-connected + unknown-action paths return structured errors.
- `allow_writes=False` by default on connectors that can mutate business
  data (Salesforce, Stripe, Zendesk, Sheets, SQL).

**Zero new runtime dependencies.** Everything new that needs a library is
an optional extra:

```bash
pip install 'shipit-agent[pdf,sql,otel]'
```

---

## How to run the verification yourself

```bash
# Fast — ~10 seconds, all 1190 tests.
pytest

# Bedrock E2E (from 1.0.6, still passing).
SHIPIT_BEDROCK_E2E=1 pytest tests/test_autopilot_bedrock_e2e.py

# Long-running Autopilot soak (arbitrary duration).
SHIPIT_AUTOPILOT_SOAK=300 pytest tests/test_autopilot_long_task.py::test_bedrock_soak_for_requested_duration
```

---

## Upgrade

```bash
pip install --upgrade shipit-agent==1.0.7
```

**No breaking changes.** Existing code, notebooks, Autopilot runs, and
checkpoints from 1.0.6 all continue to work. The twelve new tools are
opt-in — import and instantiate what you need:

```python
from shipit_agent import (
    GitHubTool, GitLabTool, SQLTool, VisionTool, PDFTool,
    FigmaTool, SalesforceTool, StripeTool,
    GoogleSheetsTool, ZendeskTool, LinkedInSearchTool,
)
from shipit_agent.tracing_exporters import LangSmithExporter, OpenTelemetryExporter
```
