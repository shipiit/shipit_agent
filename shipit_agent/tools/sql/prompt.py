from __future__ import annotations

SQL_PROMPT = """

## sql
Query a relational database through SQLAlchemy. Works against PostgreSQL,
MySQL, SQLite, BigQuery, Snowflake, Redshift, MSSQL, Oracle — any dialect
the runtime has a driver installed for.

**When to use:**
- The user asks about rows, tables, counts, joins, or aggregations backed by
  a relational store.
- You need to orient yourself in an unfamiliar schema (list tables, describe
  columns, summarize).
- You are producing a report that has to be grounded in live data rather
  than assumed values.

**Decision tree:**
1. Do you know the table / column names? → `query` with a concrete SELECT.
2. Do you NOT know them? → `list_tables` first, then `describe_table` on the
   likely one, then `query`.
3. Exploring a big warehouse cold? → `schema_summary` for a top-N overview.
4. Need to write data (INSERT / UPDATE / DELETE)? → `execute`, but the tool
   rejects mutations unless it was constructed with `allow_writes=True`.
5. Big result expected? → add `LIMIT` in the SQL; the tool also caps rows at
   `max_rows` and marks the output as `truncated`.

**Rules:**
- Prefer parameterised SQL: pass values via `params={...}` and reference them
  as `:name` in the SQL. Never concatenate user input into the query string.
- Keep SELECTs focused — project only the columns you need.
- Read the `metadata.rows` for the full JSON-safe payload; the `text` field
  only shows the first 10 rows for the LLM to skim.
- If the tool returns `metadata.error`, fix the SQL or the action before
  retrying — don't retry blindly.
""".strip()
