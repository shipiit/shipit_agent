from __future__ import annotations

GOOGLE_SHEETS_PROMPT = """

## google_sheets
Read and write Google Sheets cells, ranges, formulas, and sheet structure via the
Sheets v4 REST API (sheets.googleapis.com). Writes are gated behind
`allow_writes=True` on the tool; by default the tool refuses destructive calls.

**When to use:**
- The user mentions a Google Sheet, a spreadsheet, or an A1 range like `Sheet1!A1:D10`
- Pulling tabular data into an analysis or a report
- Appending rows of data (logs, survey responses, metrics) to a tracker sheet
- Inspecting a spreadsheet's structure (tab names, sheet IDs, grid dimensions)
- Creating a new spreadsheet or adding a tab for a pipeline output

**Decision tree:**
- Reading?
  - One range → `get_values` with `spreadsheet_id` + `range` (A1 notation)
  - Multiple ranges in one round trip → `batch_get` with a list of `ranges`
  - Tab names / dimensions / sheet IDs → `get_metadata`
  - Need raw formulas instead of evaluated cells → pass `value_render_option="FORMULA"`
  - Need unformatted numbers (no thousand separators, ISO dates) → `UNFORMATTED_VALUE`
- Writing? (requires `allow_writes=True`)
  - Overwrite a fixed range → `update_values` (body: `{"values": [[...], [...]]}`)
  - Add rows to the bottom of a table → `append_values` (URL ends with `:append`)
  - Wipe a range → `clear_values` (URL ends with `:clear`)
  - Brand new workbook → `create_spreadsheet` with `title`
  - Add a tab → `add_sheet` with `spreadsheet_id` + `title` (uses `batchUpdate`)

**Rules:**
- A1 ranges contain `!` and sometimes spaces — always treat them as opaque strings,
  never split or trim them
- `values` is a list of ROWS, each row is a list of cell values — never send a flat list
- If writes are disabled the tool returns `error="writes_disabled"` without calling the API;
  do not retry, ask the operator to enable writes
- On 429 the tool returns `error="rate_limited"` with `retry_after_seconds`; back off, do not retry
- On 403 with a Google quota reason the tool returns `error="quota_exceeded"` with the
  offending quota metric name — surface it to the user, do not loop
- Never paste an access token into chat — use the configured credential record
""".strip()
