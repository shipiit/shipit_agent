"""The dashboard app blueprint."""

from __future__ import annotations

_DASHBOARD_APP = '''\
"""A dashboard: headline numbers and a bar chart, from rows you pass in.

Expects:
  rows      list of records, e.g. [{"region": "EMEA", "amount": 120000}, …]
  group_by  field to group on            (default: the first string field)
  value     numeric field to total       (default: the first numeric field)
  title     heading                      (default: "Dashboard")
  metrics   optional [{"label": …, "value": …, "note": …}] shown as cards
  output    file to write                (default: "dashboard.html")

Returns {"path": …, "totals": {...}, "grand_total": N}.
"""

import html
from pathlib import Path

_CSS = """
:root{--bg:#fff;--ink:#1c1b1a;--muted:#6f6b66;--faint:#9a958f;--line:#e8e6e3;
--accent:#e8590c;--soft:#fde3d3;--chip:#faf9f8;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#1a1918;--ink:#eceae7;
--muted:#a9a39c;--faint:#726c66;--line:#34312e;--accent:#ff8040;
--soft:#3a2418;--chip:#232120}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 var(--sans);
-webkit-font-smoothing:antialiased}
.wrap{max-width:960px;margin:0 auto;padding:44px 28px 80px}
h1{font-size:22px;font-weight:600;letter-spacing:-.02em;margin:0 0 2px}
.sub{color:var(--faint);font:13px/1.6 var(--mono);margin-bottom:30px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:14px;margin-bottom:34px}
.card{border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.card .label{font-size:13px;color:var(--muted);margin-bottom:6px}
.card .value{font-size:30px;font-weight:600;letter-spacing:-.02em;
color:var(--accent);line-height:1.15}
.card .note{font:12px/1.6 var(--mono);color:var(--faint);margin-top:4px}
.panel{border:1px solid var(--line);border-radius:14px;padding:22px 24px 12px}
.panel h2{font-size:13px;font-weight:500;color:var(--muted);margin:0 0 20px}
.bars{display:flex;align-items:flex-end;gap:14px;height:220px}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;
align-items:center;gap:8px;min-width:0}
.bar .fill{width:100%;background:var(--soft);border-radius:6px 6px 0 0;
min-height:3px}
.bar.top .fill{background:var(--accent)}
.bar .name{font:12px/1.4 var(--mono);color:var(--muted);
max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .amt{font:12px/1.4 var(--mono);color:var(--faint)}
table{border-collapse:collapse;width:100%;margin-top:26px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:9px 12px;text-align:left}
th{font-weight:600;color:var(--muted);font-size:13px}
td.num,th.num{text-align:right;font-family:var(--mono)}
footer{margin-top:34px;color:var(--faint);font:12px/1.6 var(--mono)}
"""


def _fields(rows):
    """Guess the grouping and value fields from the data itself."""
    text_field = number_field = None
    for key, value in (rows[0] if rows else {}).items():
        if number_field is None and _number(value) is not None:
            number_field = key
        elif text_field is None:
            text_field = key
    return text_field, number_field


def _number(value):
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _money(value):
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.0f}K"
    return f"${value:,.0f}"


def run(input, env):
    rows = input.get("rows") or []
    if not rows:
        raise ValueError("pass `rows`: a list of records to chart")

    guessed_group, guessed_value = _fields(rows)
    group_by = input.get("group_by") or guessed_group
    value_key = input.get("value") or guessed_value
    if not group_by or not value_key:
        raise ValueError("could not find a label field and a numeric field")

    totals = {}
    for row in rows:
        amount = _number(row.get(value_key)) or 0.0
        totals[str(row.get(group_by, ""))] = (
            totals.get(str(row.get(group_by, "")), 0.0) + amount
        )
    grand = sum(totals.values())
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    peak = ordered[0][1] if ordered else 0

    metrics = input.get("metrics") or [
        {"label": f"Total {value_key}", "value": _money(grand),
         "note": f"{len(rows)} rows"},
        {"label": f"Top {group_by}", "value": ordered[0][0] if ordered else "—",
         "note": _money(peak) if ordered else ""},
        {"label": f"{group_by.title()}s", "value": str(len(totals)),
         "note": "grouped"},
    ]
    cards = "".join(
        f"<div class=card><div class=label>{html.escape(str(m.get('label','')))}"
        f"</div><div class=value>{html.escape(str(m.get('value','')))}</div>"
        f"<div class=note>{html.escape(str(m.get('note','')))}</div></div>"
        for m in metrics
    )

    bars = "".join(
        f"<div class='bar{' top' if index == 0 else ''}'>"
        f"<div class=amt>{_money(amount)}</div>"
        f"<div class=fill style='height:{(amount / peak * 100) if peak else 0:.1f}%'>"
        f"</div><div class=name>{html.escape(name)}</div></div>"
        for index, (name, amount) in enumerate(ordered)
    )

    body = "".join(
        f"<tr><td>{html.escape(name)}</td>"
        f"<td class=num>{amount:,.0f}</td>"
        f"<td class=num>{(amount / grand * 100) if grand else 0:.1f}%</td></tr>"
        for name, amount in ordered
    )

    title = input.get("title", "Dashboard")
    page = (
        f"<!doctype html><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style>"
        f"<div class=wrap><h1>{html.escape(title)}</h1>"
        f"<div class=sub>{html.escape(str(input.get('subtitle', '')))}</div>"
        f"<div class=cards>{cards}</div>"
        f"<div class=panel><h2>{html.escape(value_key)} by "
        f"{html.escape(group_by)}</h2><div class=bars>{bars}</div></div>"
        f"<table><tr><th>{html.escape(group_by)}</th>"
        f"<th class=num>{html.escape(value_key)}</th><th class=num>share</th></tr>"
        f"{body}</table>"
        f"<footer>{len(rows)} rows · {len(totals)} groups</footer></div>"
    )
    out = Path(input.get("output", "dashboard.html"))
    out.write_text(page, encoding="utf-8")
    return {"path": str(out.resolve()), "totals": totals, "grand_total": grand}
'''

