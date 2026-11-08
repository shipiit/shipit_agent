---
title: sql
description: One SQLAlchemy-backed tool covering every dialect — read-safe by default, mutation opt-in, with schema exploration actions for cold starts.
---

# `sql`

A single tool that talks to any SQLAlchemy-compatible database —
PostgreSQL, MySQL, SQLite, BigQuery, Snowflake, Redshift, MSSQL,
Oracle — as long as the driver is installed. Reads are safe by
default (the tool refuses anything but `SELECT` / `WITH ... SELECT`),
mutation is opt-in per tool instance, and a cold start can explore
the schema before querying.

> **TL;DR** —
> `SQLTool(url="postgresql://user:pass@host/db").run(ctx, action="query", sql="SELECT 1")`
> returns a markdown table in `output.text` plus the full rows in
> `metadata.rows`. Set `allow_writes=True` to unlock `execute`.

## When to use

- **Finance / revenue reports** grounded in live data —
  `action="query"` against a warehouse view.
- **Schema explorer** for an unfamiliar DB —
  `list_tables` → `describe_table` → `query`.
- **Warehouse preflight** — `schema_summary` gives a cheap top-N
  table / column-count overview before you burn tokens guessing.
- **Controlled mutation jobs** (backfills, maintenance cleanups) on
  a dedicated `SQLTool(allow_writes=True)` instance gated behind
  `human_review`.

## Setup

`SQLTool` is **not** a connector — no `CredentialRecord` involved.
Credentials go into the SQLAlchemy URL (or a pre-built `Engine`):

```bash
pip install 'shipit-agent[sql]'          # pulls sqlalchemy >= 2.0
# and whichever dialect you need, e.g.
pip install 'psycopg[binary]'            # PostgreSQL
pip install 'pymysql'                    # MySQL
pip install 'sqlalchemy-bigquery'        # BigQuery
```

```python
from shipit_agent.tools.sql import SQLTool

# Option 1 — URL
sql = SQLTool(url="postgresql+psycopg://user:pass@host:5432/db")

# Option 2 — pre-built engine (reuse pooling from the rest of your app)
from sqlalchemy import create_engine
engine = create_engine("bigquery://my-project", echo=False)
sql = SQLTool(engine=engine)

# Option 3 — pick up URL from context state
sql = SQLTool()
# later:
ctx = ToolContext(prompt="demo", state={"sql_url": "sqlite:///:memory:"})
```

Construction is cheap: **SQLAlchemy is lazy-imported on the first
`run()`**, not at construction, so building a `SQLTool` in a factory
doesn't force the dependency on unrelated agents.

## Safety posture

| Knob | Default | What it does |
| --- | --- | --- |
| `allow_writes` | `False` | When false, `action="query"` rejects anything but `SELECT` / `WITH ... SELECT` / `(` via a regex that scans the first 500 chars for `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `REPLACE`, `GRANT`, `REVOKE`, `MERGE`. `execute` is disabled entirely. |
| `max_rows` | `500` | Cap on rows returned by `query`. Overflow is dropped and `metadata.truncated = True`. |
| `timeout_seconds` | `30` | Reserved for per-connection `execution_options` in dialects that support it. |

Exceptions are always caught and surfaced as structured metadata —
`run()` never raises.

## Quick example

```python
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.sql import SQLTool

sql = SQLTool(url="sqlite:///./demo.db", max_rows=200)
ctx = ToolContext(prompt="demo")

out = sql.run(ctx, action="query",
              sql="SELECT region, SUM(arr) AS arr FROM accounts GROUP BY region ORDER BY arr DESC")
print(out.text)
# | region | arr   |
# | ---    | ---   |
# | EU     | 2400  |
# | NA     | 1800  |
# ...

# Full JSON-safe rows are in metadata
for row in out.metadata["rows"][:3]:
    print(row)
```

## As a tool handed to an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import OpenAIChatLLM
from shipit_agent.tools.sql import SQLTool

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-5.5"),
    tools=[SQLTool(url="postgresql+psycopg://ro_user:...@analytics-replica/prod")],
    prompt=(
        "You are a revenue analyst. Use the sql tool to answer questions "
        "with live data. Prefer parameterised queries (:name) over string "
        "interpolation."
    ),
)
agent.run("What was Q3 ARR by region? Show the top 5.")
```

## Actions

Five actions live on a single `action` enum.

### `query`

Read-only SELECT (plus `WITH ... SELECT` CTEs). Required: `sql`.
Optional: `params` (dict for `:named` placeholders).

```python
sql.run(ctx, action="query",
        sql="SELECT id, email FROM users WHERE created_at > :since LIMIT 20",
        params={"since": "2026-01-01"})
```

Output `text` renders the first 10 rows as a markdown table for LLM
skimming; `metadata.rows` carries the full (up to `max_rows`)
JSON-safe payload. Decimals become floats, dates become ISO strings,
bytes become `base64:...`, exotic types fall back to `str(value)`.
If the result exceeded `max_rows`, `metadata.truncated = True` and
`metadata.total_before_truncation` is set.

### `execute`

Mutation (INSERT / UPDATE / DELETE / DDL). Required: `sql`. Optional:
`params`. Disabled unless the tool was constructed with
`allow_writes=True`; otherwise returns `writes_disabled`. Runs inside
`engine.begin()` so success commits and SQLAlchemy errors roll back.

```python
write = SQLTool(url=DB_URL, allow_writes=True)
write.run(ctx, action="execute",
          sql="UPDATE users SET plan = :plan WHERE id = :id",
          params={"plan": "pro", "id": 42})
# text: "OK. rowcount=1"
```

### `list_tables`

No required params. Returns a bullet list of table names plus
`metadata.tables`.

### `describe_table`

Required: `table`. Optional: `schema` (qualifier on dialects that
have one). Returns per-column `name`, `type`, `nullable`, `default`,
`primary_key`.

```python
sql.run(ctx, action="describe_table", table="users")
```

### `schema_summary`

Required: none. Optional: `limit` (default 50). Returns a top-N
`table (column_count cols)` summary, useful for cheaply introducing
a cold warehouse to the LLM.

## Error shapes

| `error=` | Meaning | What to do |
| --- | --- | --- |
| `sqlalchemy_missing` | SQLAlchemy isn't installed | `pip install 'shipit-agent[sql]'`. |
| `no_connection` | No `url=`, `engine=`, or `context.state["sql_url"]` resolvable | Pass one. |
| `engine_error` | `create_engine(url)` failed | Usually a malformed URL or missing dialect driver. |
| `bad_action` | `action=` value not in the enum | Use `query` / `execute` / `list_tables` / `describe_table` / `schema_summary`. |
| `missing_sql` | `action="query"` or `"execute"` without `sql` | Provide the statement. |
| `write_not_allowed` | `query` saw a mutation keyword and `allow_writes=False` | Either switch to `execute` on an `allow_writes=True` tool, or rephrase as a pure SELECT. |
| `writes_disabled` | `action="execute"` on an `allow_writes=False` tool | Construct a separate `SQLTool(allow_writes=True)` for the mutation surface. |
| `sql_error` | SQLAlchemy raised (syntax, constraint, timeout, …) | `metadata.message` carries the driver message; `metadata.sql` has the first 200 chars of the offending statement. |
| `missing_table` | `describe_table` without `table` | Provide it. |

## Related

- [Tool catalog](index.md) — every built-in tool.
- [Read file](read-file.md) / [Grep files](grep-files.md) — for
  exploring repos instead of databases.
- [Specialists](../autopilot/specialists.md) — data / analyst roles
  that chain `schema_summary` → `describe_table` → `query`.
