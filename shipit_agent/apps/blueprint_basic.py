"""The report, table and page app blueprints."""

from __future__ import annotations

_REPORT_APP = '''\
"""A report over rows the caller passes in."""


def run(input, env):
    rows = input.get("rows") or []
    if not rows:
        return {"markdown": "_no rows_", "count": 0}

    columns = list(rows[0])
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(c, "")) for c in columns) + " |"
        for row in rows
    ]
    return {"markdown": "\\n".join([header, divider, *body]), "count": len(rows)}
'''


_TABLE_APP = '''\
"""Read a CSV and answer questions about it, every time it is run."""

import csv
from pathlib import Path


def run(input, env):
    # A model will call this `path`, `file` or `csv` depending on the day.
    location = input.get("path") or input.get("file") or input.get("csv")
    if not location:
        raise KeyError("pass the CSV location as `path`")
    path = Path(location)
    with path.open() as handle:
        rows = list(csv.DictReader(handle))

    # `group_by` is the documented name; `column` is what a model reaches for
    # half the time. Accepting both costs nothing and saves a retry.
    column = input.get("group_by") or input.get("column")
    if not column:
        return {"rows": len(rows), "columns": list(rows[0]) if rows else []}

    counts = {}
    for row in rows:
        counts[row.get(column, "")] = counts.get(row.get(column, ""), 0) + 1
    return {"rows": len(rows), "group_by": column, "counts": counts}
'''


_PAGE_APP = '''\
"""Render a self-contained HTML page from data, and write it beside the app."""

import html
from pathlib import Path


def run(input, env):
    title = input.get("title", "Report")
    rows = input.get("rows") or []
    cells = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values())
        + "</tr>"
        for row in rows
    )
    head = "".join(f"<th>{html.escape(c)}</th>" for c in (rows[0] if rows else {}))
    page = (
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
        "<style>body{font:15px/1.6 system-ui;margin:40px;max-width:720px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #e8e6e3;padding:8px 10px;text-align:left}"
        "th{font-weight:600}</style>"
        f"<h1>{html.escape(title)}</h1><table><tr>{head}</tr>{cells}</table>"
    )
    out = Path(input.get("output", "page.html"))
    out.write_text(page, encoding="utf-8")
    return {"path": str(out.resolve()), "bytes": len(page), "rows": len(rows)}
'''

