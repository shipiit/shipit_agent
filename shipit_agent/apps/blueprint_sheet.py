"""The sheet app blueprint."""

from __future__ import annotations

_SHEET_APP = '''\
"""A spreadsheet view of rows — column letters, row numbers, a frozen header.

Expects:
  rows     list of records
  title    sheet name        (default: "Sheet")
  output   file to write     (default: "sheet.html")
  highlight optional {column: {value: "at risk"}} to tint matching cells

Returns {"path": …, "rows": N, "columns": [...]}.
"""

import html
from pathlib import Path

_CSS = """
:root{--bg:#fff;--ink:#1c1b1a;--muted:#6f6b66;--faint:#9a958f;--line:#e3e1de;
--head:#2f5bd8;--gridbg:#fafafa;--warn:#fdece2;--warn-ink:#b5470c;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#1a1918;--ink:#eceae7;
--muted:#a9a39c;--faint:#726c66;--line:#34312e;--gridbg:#201e1d;
--warn:#3a2418;--warn-ink:#ff9d66}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans)}
.wrap{padding:26px 28px 60px}
h1{font-size:17px;font-weight:600;margin:0 0 3px}
.meta{color:var(--faint);font:12px/1.6 var(--mono);margin-bottom:18px}
.grid{border:1px solid var(--line);border-radius:10px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-right:1px solid var(--line);border-bottom:1px solid var(--line);
padding:8px 12px;text-align:left;white-space:nowrap}
tr th:last-child,tr td:last-child{border-right:none}
thead.letters th{background:var(--gridbg);color:var(--faint);
font:11px/1.5 var(--mono);font-weight:400;text-align:center;
position:sticky;top:0;z-index:2}
thead.names th{background:var(--head);color:#fff;font-weight:600;
position:sticky;top:26px;z-index:2}
td.rownum,th.rownum{background:var(--gridbg);color:var(--faint);
font:11px/1.5 var(--mono);text-align:center;width:38px;
position:sticky;left:0}
td.warn{background:var(--warn);color:var(--warn-ink);font-weight:500}
tbody tr:hover td:not(.rownum){background:var(--gridbg)}
.tab{display:inline-block;margin-top:14px;padding:6px 14px;
border:1px solid var(--line);border-radius:8px 8px 0 0;
font-size:13px;font-weight:500}
"""

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _column_name(index):
    name = ""
    while True:
        name = _LETTERS[index % 26] + name
        index = index // 26 - 1
        if index < 0:
            return name


def run(input, env):
    rows = input.get("rows") or []
    if not rows:
        raise ValueError("pass `rows`: a list of records")
    columns = list(rows[0])
    highlight = input.get("highlight") or {}

    letters = "".join(
        f"<th>{_column_name(i)}</th>" for i in range(len(columns))
    )
    names = "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)

    body = []
    for number, row in enumerate(rows, start=2):
        cells = []
        for column in columns:
            value = str(row.get(column, ""))
            flagged = value in (highlight.get(column) or {})
            cells.append(
                f"<td class=warn>{html.escape(value)}</td>" if flagged
                else f"<td>{html.escape(value)}</td>"
            )
        body.append(
            f"<tr><td class=rownum>{number}</td>{''.join(cells)}</tr>"
        )

    title = input.get("title", "Sheet")
    page = (
        f"<!doctype html><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style>"
        f"<div class=wrap><h1>{html.escape(title)}</h1>"
        f"<div class=meta>{len(rows)} rows · {len(columns)} columns</div>"
        f"<div class=grid><table>"
        f"<thead class=letters><tr><th class=rownum></th>{letters}</tr></thead>"
        f"<thead class=names><tr><th class=rownum>1</th>{names}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
        f"<div class=tab>{html.escape(title)}</div></div>"
    )
    out = Path(input.get("output", "sheet.html"))
    out.write_text(page, encoding="utf-8")
    return {"path": str(out.resolve()), "rows": len(rows), "columns": columns}
'''

