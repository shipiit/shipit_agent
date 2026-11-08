"""The workflow app blueprint."""

from __future__ import annotations

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

