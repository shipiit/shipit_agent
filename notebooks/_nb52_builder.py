"""Build notebooks/52_analyst_sql_to_dashboard.ipynb.

Data-analyst persona: ask a SQL question of a seeded SQLite database and
render both a markdown table (in-notebook) and a dashboard HTML
(artifact).

Unlike the other notebooks in this set, this one runs the tool against a
REAL in-memory SQLite engine — no stubbing required (SQLAlchemy + sqlite3
are stdlib-level).

Run ``python notebooks/_nb52_builder.py`` to regenerate the notebook.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "52_analyst_sql_to_dashboard.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": text.splitlines(keepends=True),
    }


CELLS: list[dict] = [
    md(
        "# 52 · Data Analyst — SQL Question to Dashboard\n"
        "\n"
        "**Persona:** Data analyst. **Tools exercised:** `SQLTool` (real "
        "SQLite), `DashboardRenderTool`.\n"
        "\n"
        "Unlike the other persona notebooks, this one does **not** stub the "
        "database — we spin up an in-memory SQLite engine, seed it with a "
        "small sales table, then drive `SQLTool` against it for real. That "
        "gives you one notebook where the tool actually executes a query.\n"
        "\n"
        "Workflow:\n"
        "\n"
        "1. Create + seed an in-memory SQLite database.\n"
        "2. Inspect the schema via the tool (list_tables + describe_table).\n"
        "3. Run a SQL query through the tool to answer a question.\n"
        "4. Render the answer as a dashboard HTML artifact.\n"
    ),
    md("## Setup"),
    code(
        "from pathlib import Path\n"
        "\n"
        "def _find_notebooks_dir() -> Path:\n"
        "    cwd = Path.cwd().resolve()\n"
        "    if cwd.name == 'notebooks':\n"
        "        return cwd\n"
        "    candidate = cwd / 'notebooks'\n"
        "    return candidate if candidate.is_dir() else cwd\n"
        "WORKSPACE = _find_notebooks_dir() / '_analyst_workspace'\n"
        "WORKSPACE.mkdir(parents=True, exist_ok=True)\n"
        "print('workspace:', WORKSPACE)\n"
    ),
    md("## 1 · Pick a model"),
    code(
        "# from shipit_agent.llms import build_llm_from_settings\n"
        "# llm = build_llm_from_settings({'provider': 'bedrock',\n"
        "#     'model': 'bedrock/openai.gpt-oss-120b-1:0'}, provider='bedrock')\n"
        "# llm = build_llm_from_settings({'provider': 'litellm',\n"
        "#     'model': 'openai/gpt-4o-mini'}, provider='litellm')\n"
        "# from shipit_agent.llms import LiteLLMProxyChatLLM\n"
        "# llm = LiteLLMProxyChatLLM(model='gpt-4o-mini',\n"
        "#     api_base='https://litellm.internal', api_key='sk-proxy')\n"
        "\n"
        "from shipit_agent.llms import SimpleEchoLLM\n"
        "llm = SimpleEchoLLM()\n"
        "print('llm:', type(llm).__name__)\n"
    ),
    md(
        "## 2 · Seed a real in-memory SQLite\n"
        "\n"
        "This runs a small `orders` table straight through SQLAlchemy. "
        "`SQLTool` is lazy about SQLAlchemy — it only imports it on first "
        "`run()`. If you don't have SQLAlchemy installed (`pip install "
        "'shipit-agent[sql]'`), the tool returns a structured "
        "`sqlalchemy_missing` output rather than raising.\n"
    ),
    code(
        "try:\n"
        "    from sqlalchemy import create_engine, text\n"
        "    HAS_SQLALCHEMY = True\n"
        "except ImportError:  # pragma: no cover - ci installs it\n"
        "    HAS_SQLALCHEMY = False\n"
        "    print('SQLAlchemy not installed — skipping seed. '\n"
        "          'Install with: pip install shipit-agent[sql]')\n"
        "\n"
        "engine = None\n"
        "if HAS_SQLALCHEMY:\n"
        "    engine = create_engine('sqlite:///:memory:')\n"
        "    with engine.begin() as conn:\n"
        "        conn.execute(text('''\n"
        "            CREATE TABLE orders (\n"
        "              id INTEGER PRIMARY KEY,\n"
        "              region TEXT NOT NULL,\n"
        "              product TEXT NOT NULL,\n"
        "              amount_cents INTEGER NOT NULL,\n"
        "              placed_at TEXT NOT NULL\n"
        "            )\n"
        "        '''))\n"
        "        seed = [\n"
        "            (1, 'EMEA', 'Pro',   9900,  '2026-04-18'),\n"
        "            (2, 'AMER', 'Pro',   9900,  '2026-04-19'),\n"
        "            (3, 'EMEA', 'Team', 39900,  '2026-04-19'),\n"
        "            (4, 'APAC', 'Pro',   9900,  '2026-04-20'),\n"
        "            (5, 'AMER', 'Team', 39900,  '2026-04-20'),\n"
        "            (6, 'EMEA', 'Pro',   9900,  '2026-04-21'),\n"
        "            (7, 'AMER', 'Enterprise', 199900, '2026-04-21'),\n"
        "            (8, 'APAC', 'Team', 39900,  '2026-04-22'),\n"
        "            (9, 'EMEA', 'Enterprise', 199900, '2026-04-22'),\n"
        "            (10,'AMER', 'Pro',   9900,  '2026-04-23'),\n"
        "        ]\n"
        "        for row in seed:\n"
        "            conn.execute(text(\n"
        "                'INSERT INTO orders (id, region, product, amount_cents, placed_at) '\n"
        "                'VALUES (:id, :region, :product, :amount_cents, :placed_at)'\n"
        "            ), dict(zip(['id', 'region', 'product', 'amount_cents', 'placed_at'], row)))\n"
        "    print('seeded 10 orders into :memory: sqlite')\n"
    ),
    md("## 3 · Inspect schema via the tool"),
    code(
        "from shipit_agent.tools.sql import SQLTool\n"
        "from shipit_agent.tools.base import ToolContext\n"
        "\n"
        "sql_tool = SQLTool(engine=engine)\n"
        "ctx = ToolContext(prompt='analyst', state={})\n"
        "\n"
        "tables = sql_tool.run(ctx, action='list_tables')\n"
        "print('--- list_tables ---')\n"
        "print(tables.text)\n"
        "\n"
        "schema = sql_tool.run(ctx, action='describe_table', table='orders')\n"
        "print()\n"
        "print('--- describe_table orders ---')\n"
        "print(schema.text)\n"
    ),
    md(
        "## 4 · Run the analyst's question\n"
        "\n"
        "\"What is revenue by region this week, and which region leads?\"\n"
    ),
    code(
        "answer = sql_tool.run(\n"
        "    ctx, action='query',\n"
        "    sql=('SELECT region, SUM(amount_cents) / 100 AS revenue_usd, '\n"
        "         'COUNT(*) AS order_count '\n"
        "         'FROM orders '\n"
        "         \"WHERE placed_at >= '2026-04-20' \"\n"
        "         'GROUP BY region ORDER BY revenue_usd DESC'),\n"
        ")\n"
        "print(answer.text)\n"
        "rows = answer.metadata.get('rows', [])\n"
    ),
    md("## 5 · Render the answer as a dashboard"),
    code(
        "from shipit_agent.tools.dashboard_render import DashboardRenderTool\n"
        "\n"
        "dash = DashboardRenderTool(workspace_root=WORKSPACE)\n"
        "\n"
        "palette = ['#185fa5', '#1d9e75', '#534ab7']\n"
        "metric_items = [\n"
        "    {'label': r['region'], 'value': f\"${r['revenue_usd']:,}\",\n"
        "     'sub': f\"{r['order_count']} orders\"}\n"
        "    for r in rows\n"
        "]\n"
        "max_rev = max((r['revenue_usd'] for r in rows), default=1) or 1\n"
        "bars = [\n"
        "    {'label': r['region'],\n"
        "     'pct': int(round(r['revenue_usd'] / max_rev * 100)),\n"
        "     'color': palette[i % len(palette)]}\n"
        "    for i, r in enumerate(rows)\n"
        "]\n"
        "\n"
        "result = dash.run(\n"
        "    ToolContext(prompt='analyst',\n"
        "                 state={'artifact_workspace_root': str(WORKSPACE)}),\n"
        "    title='Weekly Revenue by Region',\n"
        "    subtitle='Week of 2026-04-20 — sourced from orders table',\n"
        "    lang='en',\n"
        "    sections=[\n"
        "        {'type': 'metrics', 'title': 'Region snapshot',\n"
        "         'columns': len(metric_items), 'items': metric_items},\n"
        "        {'type': 'bars', 'title': 'Revenue share', 'items': bars},\n"
        "        {'type': 'verdict', 'title': 'Answer',\n"
        "         'text': (f'**{rows[0][\"region\"]}** leads the week with '\n"
        "                  f'${rows[0][\"revenue_usd\"]:,} in revenue across '\n"
        "                  f'{rows[0][\"order_count\"]} orders.') if rows else '(no data)'},\n"
        "    ],\n"
        "    export=True,\n"
        ")\n"
        "print(result.text)\n"
        "print('artifact path:', result.metadata.get('path'))\n"
    ),
    md(
        "## Next steps\n"
        "\n"
        "* Swap the in-memory SQLite URL for your real warehouse — any "
        "SQLAlchemy URL works: `postgresql://...`, `bigquery://project`, "
        "`snowflake://...`.\n"
        "* See `docs-app/content/source/tools/sql.md` for the safety posture "
        "(`allow_writes=False` by default, `max_rows` cap, timeout).\n"
        "* Let a `GoalAgent` pick the SQL: give it the tool + "
        "`schema_summary` hint and ask it to answer the question in plain "
        "English.\n"
    ),
]


def main() -> None:
    notebook = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for i, cell in enumerate(notebook["cells"]):
        cell.setdefault("id", f"cell-{i:02d}")
    OUT.write_text(json.dumps(notebook, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
