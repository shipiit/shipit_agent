"""Apps — something the agent builds once and then *uses*.

Cloudflare OS calls these gadgets. A gadget is a small program the agent
writes into the workspace, wires resources into, and then invokes; in their
transcript it reads `Used the app`, and in their UI it opens in the sidebar.
It is the difference between an agent that answers a question and an agent
that leaves behind something you can run again tomorrow.

The same idea in Python, minus the parts that only exist because their
runtime is Durable Objects on a global network:

    app = store.create("rsvp_report", title="RSVP report",
                       blueprint="report")
    store.bind("rsvp_report", source="SHEETS", name="SHEET")
    result = run_app(app, {"month": "May"}, invoker=…, bindings=…)

An app is a **directory** with a manifest and an `app.py` exporting one
function::

    def run(input: dict, env) -> Any:
        rows = env.SHEET.read(range="A1:D50")
        return {"rows": len(rows)}

Two properties are deliberate and load-bearing:

**An app is not more privileged than the agent that wrote it.** It runs in a
subprocess with no credentials, and `env` reaches the parent over the same
capability bridge `execute_code` uses — so every resource call an app makes is
gated by the permission engine, the contracts and the approval queue exactly
as the equivalent tool call would be.

**An app only sees what it was wired.** Its `env` contains the bindings named
in its manifest, not the agent's whole environment. Wiring is an explicit act
(`set_app_binding`), recorded in the manifest, and visible in the transcript.

Blueprints are starting points, not magic: each is a file tree copied into the
new app, with a note about what the agent still has to wire up.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "App",
    "app_docstring",
    "AppManifest",
    "AppRunResult",
    "AppStore",
    "BLUEPRINTS",
    "Blueprint",
    "run_app",
]

ENTRYPOINT = "app.py"
MANIFEST = "app.json"

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def validate_name(name: str) -> str:
    """App names double as binding names and directory names.

    Rejected early and by one rule, rather than producing a directory that
    cannot later be referenced from `env`.
    """
    if not _NAME.match(name or ""):
        raise ValueError(
            f"Invalid app name {name!r}: use lower snake case, 2-41 characters, "
            "starting with a letter."
        )
    return name


@dataclass(slots=True)
class AppManifest:
    """What an app is, and what it is allowed to reach."""

    name: str
    title: str
    description: str = ""
    entrypoint: str = ENTRYPOINT
    # binding name inside the app → binding name in the agent's env
    bindings: dict[str, str] = field(default_factory=dict)
    blueprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "bindings": dict(self.bindings),
            "blueprint": self.blueprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppManifest":
        return cls(
            name=str(data.get("name") or ""),
            title=str(data.get("title") or data.get("name") or ""),
            description=str(data.get("description") or ""),
            entrypoint=str(data.get("entrypoint") or ENTRYPOINT),
            bindings=dict(data.get("bindings") or {}),
            blueprint=data.get("blueprint"),
        )


@dataclass(slots=True)
class App:
    """An app on disk."""

    path: Path
    manifest: AppManifest

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def entrypoint(self) -> Path:
        return self.path / self.manifest.entrypoint

    def files(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.path))
            for p in self.path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )

    def describe(self) -> str:
        lines = [f"{self.manifest.title} (`{self.name}`)"]
        if self.manifest.description:
            lines.append(self.manifest.description)
        lines.append(f"files    : {', '.join(self.files())}")
        wired = self.manifest.bindings
        lines.append(
            "bindings : "
            + (", ".join(f"{k} ← {v}" for k, v in sorted(wired.items())) or "none")
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Blueprint:
    """A starting file tree, plus what the agent still has to wire up."""

    id: str
    title: str
    description: str
    files: dict[str, str]
    expects: tuple[str, ...] = ()

    def notes(self) -> str:
        lines = [f"Instantiated blueprint `{self.id}` — {self.description}",
                 f"files: {', '.join(sorted(self.files))}"]
        if self.expects:
            lines.append(
                "wire these before using it: " + ", ".join(self.expects)
            )
        return "\n".join(lines)


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
        f"<div class='bar{" top" if index == 0 else ""}'>"
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

_WORKFLOW_APP = '''\
"""A workflow diagram: boxes and connectors, with one step marked live.

Expects:
  steps   [{"title": "Email", "note": "trigger", "kind": "trigger|agent|write"}]
  title   heading                 (default: "Workflow")
  status  line under the heading  (default: "")
  log     optional ["Logged RSVP from jordan@acme.com · Yes", …]
  output  file to write           (default: "workflow.html")

Returns {"path": …, "steps": N}.
"""

import html
from pathlib import Path

_CSS = """
:root{--bg:#fff;--ink:#1c1b1a;--muted:#6f6b66;--faint:#9a958f;--line:#e8e6e3;
--accent:#e8590c;--soft:#fde3d3;--ok:#2f9e44;--chip:#faf9f8;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#1a1918;--ink:#eceae7;
--muted:#a9a39c;--faint:#726c66;--line:#34312e;--accent:#ff8040;
--soft:#3a2418;--ok:#69db7c;--chip:#232120}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 var(--sans)}
.wrap{max-width:900px;margin:0 auto;padding:40px 28px 70px}
.live{display:inline-flex;align-items:center;gap:7px;background:var(--chip);
border-radius:999px;padding:5px 12px;font:12px/1 var(--mono);color:var(--ok)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor}
.status{color:var(--muted);font-size:14px;margin-left:10px}
.flow{display:flex;align-items:stretch;gap:0;margin:38px 0 8px;
flex-wrap:wrap;justify-content:center}
.step{flex:1;min-width:170px;border:1px solid var(--line);border-radius:14px;
padding:22px 18px;text-align:center;background:var(--bg)}
.step.agent{border-color:var(--accent);border-style:dashed;
background:linear-gradient(0deg,var(--bg),var(--bg))}
.icon{width:46px;height:46px;border-radius:12px;background:var(--chip);
display:flex;align-items:center;justify-content:center;margin:0 auto 12px;
font-size:20px;color:var(--muted)}
.step.agent .icon{background:var(--accent);color:#fff}
.step .title{font-weight:600;font-size:15px}
.step .note{font-size:13px;color:var(--muted);margin-top:2px}
.step.agent .note{color:var(--accent)}
.link{flex:0 0 46px;display:flex;align-items:center}
.link i{display:block;height:2px;width:100%;background:var(--accent);
opacity:.65}
.log{margin-top:34px;border-top:1px solid var(--line);padding-top:18px}
.log div{display:flex;gap:10px;align-items:baseline;color:var(--muted);
font-size:14px;padding:4px 0}
.log .bullet{color:var(--ok)}
"""

_ICONS = {"trigger": "✉", "agent": "✦", "write": "⛁", "read": "⌕",
          "send": "➤", "code": "❯"}


def run(input, env):
    steps = input.get("steps") or []
    if not steps:
        raise ValueError("pass `steps`: a list of {title, note, kind}")

    parts = []
    for index, step in enumerate(steps):
        kind = str(step.get("kind", "")).lower()
        icon = _ICONS.get(kind, "▣")
        klass = "step agent" if kind == "agent" else "step"
        parts.append(
            f"<div class='{klass}'><div class=icon>{icon}</div>"
            f"<div class=title>{html.escape(str(step.get('title', '')))}</div>"
            f"<div class=note>{html.escape(str(step.get('note', '')))}</div></div>"
        )
        if index < len(steps) - 1:
            parts.append("<div class=link><i></i></div>")

    log = "".join(
        f"<div><span class=bullet>●</span><span>{html.escape(str(line))}</span></div>"
        for line in (input.get("log") or [])
    )

    title = input.get("title", "Workflow")
    page = (
        f"<!doctype html><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style>"
        f"<div class=wrap>"
        f"<span class=live><span class=dot></span>Live</span>"
        f"<span class=status>{html.escape(title)}"
        f"{' · ' + html.escape(str(input['status'])) if input.get('status') else ''}"
        f"</span>"
        f"<div class=flow>{''.join(parts)}</div>"
        f"{f'<div class=log>{log}</div>' if log else ''}"
        f"</div>"
    )
    out = Path(input.get("output", "workflow.html"))
    out.write_text(page, encoding="utf-8")
    return {"path": str(out.resolve()), "steps": len(steps)}
'''

BLUEPRINTS: dict[str, Blueprint] = {
    "report": Blueprint(
        id="report",
        title="Markdown report",
        description="Turns a list of records into a Markdown table.",
        files={ENTRYPOINT: _REPORT_APP},
    ),
    "csv_summary": Blueprint(
        id="csv_summary",
        title="CSV summary",
        description="Reads a CSV and counts rows, optionally grouped by a column.",
        files={ENTRYPOINT: _TABLE_APP},
    ),
    "dashboard": Blueprint(
        id="dashboard",
        title="Dashboard",
        description=(
            "Headline numbers and a bar chart from records — the thing you "
            "send someone who asked where revenue landed."
        ),
        files={ENTRYPOINT: _DASHBOARD_APP},
    ),
    "sheet": Blueprint(
        id="sheet",
        title="Spreadsheet",
        description=(
            "Records as a spreadsheet: column letters, row numbers, a frozen "
            "header, and cells you can flag."
        ),
        files={ENTRYPOINT: _SHEET_APP},
    ),
    "workflow": Blueprint(
        id="workflow",
        title="Workflow diagram",
        description=(
            "A pipeline as boxes and connectors, with the agent step marked "
            "and a live log underneath."
        ),
        files={ENTRYPOINT: _WORKFLOW_APP},
    ),
    "page": Blueprint(
        id="page",
        title="HTML page",
        description=(
            "Renders a self-contained HTML page from records and writes it to "
            "disk — something you can send someone."
        ),
        files={ENTRYPOINT: _PAGE_APP},
    ),
}


def blueprint_catalogue() -> str:
    """The blueprint list, as the agent reads it."""
    return "\n".join(
        f"- `{bp.id}` — {bp.title}: {bp.description}"
        for bp in sorted(BLUEPRINTS.values(), key=lambda b: b.id)
    )


class AppStore:
    """Apps on disk, under one root."""

    def __init__(
        self, root: str | Path = ".shipit/apps", *, workdir: str | Path | None = None
    ) -> None:
        self.root = Path(root).expanduser()
        # Where an app *runs*. Not the app's own directory: an app given
        # `path="guests.csv"` means the file the agent has been working with,
        # and resolving that against the app's install directory finds
        # nothing. Defaults to the project the apps live under.
        self.workdir = Path(workdir).expanduser() if workdir else self._project_root()

    def _project_root(self) -> Path:
        """`<project>/.shipit/apps` → `<project>`; anything else → its parent."""
        root = self.root.resolve()
        if root.name == "apps" and root.parent.name == ".shipit":
            return root.parent.parent
        return root.parent

    # ── read ─────────────────────────────────────────────────────────────

    def path_for(self, name: str) -> Path:
        return self.root / validate_name(name)

    def exists(self, name: str) -> bool:
        return (self.path_for(name) / MANIFEST).exists()

    def get(self, name: str) -> App:
        path = self.path_for(name)
        manifest_path = path / MANIFEST
        if not manifest_path.exists():
            raise KeyError(f"No app named {name!r} in {self.root}")
        manifest = AppManifest.from_dict(json.loads(manifest_path.read_text()))
        return App(path=path, manifest=manifest)

    def list(self) -> list[App]:
        if not self.root.exists():
            return []
        apps = []
        for child in sorted(self.root.iterdir()):
            if (child / MANIFEST).exists():
                apps.append(self.get(child.name))
        return apps

    # ── write ────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        *,
        title: str,
        description: str = "",
        files: dict[str, str] | None = None,
        blueprint: str | None = None,
        overwrite: bool = False,
    ) -> App:
        """Create an app from a blueprint, explicit files, or both.

        Explicit files win over blueprint files of the same name, so an agent
        can start from a blueprint and replace just the entrypoint.
        """
        validate_name(name)
        path = self.path_for(name)
        if path.exists() and not overwrite and (path / MANIFEST).exists():
            raise FileExistsError(f"App {name!r} already exists at {path}")

        contents: dict[str, str] = {}
        if blueprint is not None:
            if blueprint not in BLUEPRINTS:
                raise KeyError(
                    f"Unknown blueprint {blueprint!r}. Available: "
                    f"{', '.join(sorted(BLUEPRINTS))}"
                )
            contents.update(BLUEPRINTS[blueprint].files)
        contents.update(files or {})
        if ENTRYPOINT not in contents:
            raise ValueError(
                f"An app needs {ENTRYPOINT} defining `run(input, env)` — pass it "
                "in files, or start from a blueprint."
            )

        path.mkdir(parents=True, exist_ok=True)
        for relative, body in contents.items():
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

        manifest = AppManifest(
            name=name, title=title, description=description, blueprint=blueprint
        )
        self._write_manifest(path, manifest)
        return App(path=path, manifest=manifest)

    def run(self, name: str, payload: dict[str, Any] | None = None, **kwargs: Any):
        """Run one of this store's apps, where this store's apps run.

        :func:`run_app` on its own defaults to the app's install directory,
        which is right for an app that only touches its own files and wrong
        for one handed ``path="bookings.csv"``. Going through the store keeps
        the working directory consistent with what the agent's own tools see.
        """
        kwargs.setdefault("cwd", self.workdir)
        return run_app(self.get(name), payload, **kwargs)

    def bind(self, name: str, *, source: str, as_name: str | None = None) -> App:
        """Wire one of the agent's bindings into the app's own env."""
        app = self.get(name)
        app.manifest.bindings[as_name or source] = source
        self._write_manifest(app.path, app.manifest)
        return app

    def unbind(self, name: str, as_name: str) -> App:
        app = self.get(name)
        app.manifest.bindings.pop(as_name, None)
        self._write_manifest(app.path, app.manifest)
        return app

    def delete(self, name: str) -> None:
        import shutil

        path = self.path_for(name)
        if path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _write_manifest(path: Path, manifest: AppManifest) -> None:
        (path / MANIFEST).write_text(
            json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
        )


# ── running ──────────────────────────────────────────────────────────────


def app_docstring(app: "App") -> str:
    """The app's module docstring — what it expects, in its own words.

    Returned to the agent when a run fails, because "the app raised KeyError"
    without saying what the app wanted costs a retry that guessing cannot fix.
    """
    try:
        source = app.entrypoint.read_text(encoding="utf-8")
    except OSError:
        return ""
    import ast

    try:
        return (ast.get_docstring(ast.parse(source)) or "").strip()
    except SyntaxError:
        return ""


@dataclass(slots=True)
class AppRunResult:
    ok: bool
    value: Any = None
    stdout: str = ""
    error: str = ""
    exit_code: int | None = 0
    timed_out: bool = False
    env_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "stdout": self.stdout,
            "error": self.error,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "env_calls": self.env_calls,
        }


_RUNNER = '''\
import json, runpy, sys, traceback

_payload = json.loads(sys.stdin.read() or "{}")
_module = runpy.run_path(_payload["entrypoint"])
_run = _module.get("run")
if _run is None:
    print(json.dumps({"__shipit_error__": "app.py does not define run(input, env)"}),
          file=sys.stderr)
    raise SystemExit(2)

try:
    _value = _run(_payload.get("input") or {}, env)
except Exception:
    print(json.dumps({"__shipit_error__": traceback.format_exc(limit=6)}),
          file=sys.stderr)
    raise SystemExit(1)

try:
    _encoded = json.dumps(_value, default=str)
except (TypeError, ValueError):
    _encoded = json.dumps(str(_value))
print("__SHIPIT_APP_RESULT__" + _encoded)
'''


def run_app(
    app: App,
    payload: dict[str, Any] | None = None,
    *,
    invoker: Any = None,
    bindings: dict[str, Any] | None = None,
    timeout_seconds: float = 60.0,
    python: str | None = None,
    cwd: str | Path | None = None,
) -> AppRunResult:
    """Run *app* in a subprocess and return what its ``run()`` returned.

    ``env`` inside the app carries only the bindings the manifest names, and
    every call on it crosses the capability bridge back to the parent's
    permission engine. With no ``invoker`` the app still runs — it simply has
    no `env`, which is the right outcome for an app that never asked for one.
    """
    from shipit_agent.codemode.bridge import BridgeServer
    from shipit_agent.codemode.preamble import build_preamble

    wired = _wired_bindings(app, bindings or {})
    missing = sorted(set(app.manifest.bindings) - set(wired))
    source = build_preamble(wired) + "\n" + _RUNNER

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    bridge: Any = None
    if invoker is not None:
        bridge = BridgeServer(invoker)
        bridge.start()
        child_env.update(bridge.address.as_env())

    try:
        with tempfile.TemporaryDirectory(prefix="shipit-app-") as workdir:
            script = Path(workdir) / "_runner.py"
            script.write_text(source, encoding="utf-8")
            stdin = json.dumps(
                {"entrypoint": str(app.entrypoint), "input": payload or {}}
            )
            try:
                completed = subprocess.run(
                    [python or sys.executable, "-I", str(script)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=str(cwd or app.path),
                    env=child_env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return AppRunResult(
                    ok=False,
                    error=f"app timed out after {timeout_seconds:.0f}s",
                    exit_code=None,
                    timed_out=True,
                )
    finally:
        if bridge is not None:
            bridge.stop()

    result = _parse(completed.stdout, completed.stderr, completed.returncode)
    result.env_calls = bridge.call_count if bridge is not None else 0
    if missing and not result.ok:
        result.error += (
            f"\n(the manifest wires {', '.join(missing)}, which the agent's "
            "environment does not currently offer)"
        )
    return result


def _wired_bindings(app: App, available: dict[str, Any]) -> dict[str, Any]:
    """The app's env: only what its manifest names, under the names it chose."""
    wired: dict[str, Any] = {}
    for inner, outer in app.manifest.bindings.items():
        binding = available.get(outer)
        if binding is not None:
            wired[inner] = binding
    return wired


def _parse(stdout: str, stderr: str, code: int) -> AppRunResult:
    marker = "__SHIPIT_APP_RESULT__"
    value: Any = None
    lines = []
    for line in (stdout or "").splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
            except ValueError:
                value = line[len(marker):]
        else:
            lines.append(line)

    error = ""
    for line in (stderr or "").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            error += line + "\n"
            continue
        if isinstance(payload, dict) and "__shipit_error__" in payload:
            error += str(payload["__shipit_error__"])
        else:
            error += line + "\n"

    return AppRunResult(
        ok=code == 0 and not error.strip(),
        value=value,
        stdout="\n".join(lines).strip(),
        error=error.strip(),
        exit_code=code,
    )
