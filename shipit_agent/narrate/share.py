"""Render a run as a standalone HTML transcript.

The same rows the terminal renderer produces, in a single self-contained file
you can send to someone. No network requests, no build step, no JavaScript
beyond the disclosure toggles — so it opens from a file:// URL, survives being
emailed, and renders identically in ten years.

    from shipit_agent.narrate.share import write_transcript
    write_transcript("run.html", result.events, model="claude-opus-5")

Or from the CLI::

    shipit code --share run.html "fix the failing test"
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable

from .grouping import ApprovalRow, NoticeRow, ProseRow, WorkRow, build_transcript

__all__ = ["render_transcript_html", "write_transcript"]

# Deliberately close to the reference UI: warm orange accent, near-black text
# on off-white, work rows recessed into grey. Dark mode via a media query,
# because a transcript is as likely to be read at night as at a desk.
_STYLE = """
:root {
  --bg: #fdfdfc; --surface: #fff; --line: #e8e6e3;
  --text: #1c1b1a; --muted: #6f6b66; --faint: #9a958f;
  --accent: #e8590c; --accent-soft: #fdf0e8;
  --danger: #c92a2a; --ok: #2f9e44;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1918; --surface: #232120; --line: #34312e;
    --text: #eceae7; --muted: #a9a39c; --faint: #726c66;
    --accent: #ff8040; --accent-soft: #2e1f16;
    --danger: #ff8787; --ok: #69db7c;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.6 var(--sans);
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 760px; margin: 0 auto; padding: 48px 24px 96px; }
header { border-bottom: 1px solid var(--line); padding-bottom: 20px; margin-bottom: 28px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.01em; }
.meta { color: var(--faint); font: 12px/1.5 var(--mono); }
.prose { margin: 20px 0; white-space: pre-wrap; }
.work { margin: 14px 0; }
.work summary {
  cursor: pointer; list-style: none; display: flex; gap: 10px;
  align-items: baseline; color: var(--muted); font-size: 14px;
  padding: 3px 6px; margin-left: -6px; border-radius: 7px;
}
.work summary::-webkit-details-marker { display: none; }
.work summary:hover { color: var(--text); background: var(--surface); }
.glyph { color: var(--faint); flex: 0 0 auto; font-family: var(--mono); }
.label { flex: 1 1 auto; min-width: 0; }
.caret { color: var(--faint); flex: 0 0 auto; transition: transform .15s ease; }
.work[open] .caret { transform: rotate(90deg); }
.detail { font: 12px/1.5 var(--mono); color: var(--faint); margin: 2px 0 0 30px; }
.body {
  margin: 8px 0 0 30px; padding: 12px 14px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 12px;
  font: 12px/1.6 var(--mono); white-space: pre-wrap; overflow-x: auto;
}
.call { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
.call:first-child { border-top: 0; padding-top: 0; margin-top: 0; }
.call-name { color: var(--text); font-weight: 600; }
.err { color: var(--danger); }
.badge {
  font: 600 10px/1 var(--sans); text-transform: uppercase; letter-spacing: .05em;
  padding: 3px 7px; border-radius: 999px; background: var(--accent-soft);
  color: var(--accent); flex: 0 0 auto;
}
.approval {
  margin: 18px 0; padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: 12px;
}
.approval .title { font-weight: 600; }
.approval .tag { color: var(--faint); font: 12px/1.5 var(--mono); margin-top: 2px; }
.notice { color: var(--faint); font-size: 13px; margin: 14px 0; }
footer {
  margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line);
  color: var(--faint); font: 12px/1.5 var(--mono); text-align: right;
}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _work_html(row: WorkRow) -> str:
    group = row.group
    badge = '<span class="badge">error</span>' if group.has_error else ""
    detail = (
        f'<div class="detail">{_esc(" · ".join(group.detail_lines))}</div>'
        if group.detail_lines
        else ""
    )

    calls = []
    for call in group.calls:
        body = call.error or call.output or "(no output)"
        status = "err" if call.status in ("error", "denied") else ""
        calls.append(
            f'<div class="call">'
            f'<span class="call-name {status}">{_esc(call.past_label())}</span>'
            f"{f' · {call.duration_ms:.0f}ms' if call.duration_ms else ''}"
            f"\n{_esc(body[:4000])}</div>"
        )

    return (
        f'<details class="work">'
        f"<summary>"
        f'<span class="glyph">{_esc(group.icon)}</span>'
        f'<span class="label">{_esc(group.label)}{detail}</span>'
        f"{badge}"
        f'<span class="caret">›</span>'
        f"</summary>"
        f'<div class="body">{"".join(calls)}</div>'
        f"</details>"
    )


def _approval_html(row: ApprovalRow) -> str:
    state = (
        "auto-approved"
        if row.auto_approved
        else "awaiting approval"
    )
    tag = f"#{row.action_id} · {_esc(row.tag)}" if row.tag else f"#{row.action_id}"
    return (
        f'<div class="approval">'
        f'<div class="title">{_esc(row.title)}</div>'
        f'<div class="tag">{tag} · {state}</div>'
        f"</div>"
    )


def render_transcript_html(
    source: Any,
    *,
    title: str = "Agent run",
    model: str | None = None,
    prompt: str | None = None,
) -> str:
    """Render a run's events as one self-contained HTML document."""
    events = list(getattr(source, "events", source))
    rows = build_transcript(events)

    usage: dict[str, Any] = {}
    started = ""
    for event in events:
        if event.type in ("run_completed", "usage_tick"):
            usage = dict(event.payload.get("usage") or usage)
        if event.type == "run_started" and not prompt:
            prompt = str(event.payload.get("prompt") or "")
        if not started:
            started = str(event.timestamp)

    body: list[str] = []
    for row in rows:
        if isinstance(row, WorkRow):
            body.append(_work_html(row))
        elif isinstance(row, ProseRow):
            body.append(f'<div class="prose">{_esc(row.text)}</div>')
        elif isinstance(row, ApprovalRow):
            body.append(_approval_html(row))
        elif isinstance(row, NoticeRow):
            body.append(f'<div class="notice">◈ {_esc(row.text)}</div>')

    tokens = int(usage.get("total_tokens") or 0) or (
        int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    )
    footer_parts = [f"{tokens:,} tokens"] if tokens else []
    if model:
        footer_parts.append(model)
    footer = " · ".join(footer_parts)

    meta_parts = []
    if prompt:
        meta_parts.append(_esc(prompt[:300]))

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_STYLE}</style>
</head><body>
<div class="wrap">
<header>
  <h1>{_esc(title)}</h1>
  <div class="meta">{"<br>".join(meta_parts)}</div>
</header>
{"".join(body)}
<footer>{_esc(footer)}</footer>
</div>
</body></html>
"""


def write_transcript(
    path: str | Path,
    source: Any,
    *,
    title: str = "Agent run",
    model: str | None = None,
) -> Path:
    """Write the transcript to *path* and return the resolved path."""
    target = Path(path).expanduser()
    if target.suffix.lower() not in (".html", ".htm"):
        target = target.with_suffix(".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_transcript_html(source, title=title, model=model), encoding="utf-8"
    )
    return target.resolve()


def transcript_json(source: Any) -> str:
    """The same rows as JSON, for a caller building its own view."""
    rows: list[dict[str, Any]] = []
    for row in build_transcript(source):
        if isinstance(row, WorkRow):
            rows.append({
                "type": "work",
                "label": row.group.label,
                "icon": row.group.icon,
                "details": row.group.detail_lines,
                "error": row.group.has_error,
                "calls": [
                    {
                        "tool": c.name,
                        "label": c.past_label(),
                        "status": c.status,
                        "duration_ms": c.duration_ms,
                    }
                    for c in row.group.calls
                ],
            })
        elif isinstance(row, ProseRow):
            rows.append({"type": "prose", "text": row.text})
        elif isinstance(row, ApprovalRow):
            rows.append({
                "type": "approval",
                "action_id": row.action_id,
                "title": row.title,
                "tag": row.tag,
                "auto_approved": row.auto_approved,
            })
        elif isinstance(row, NoticeRow):
            rows.append({"type": "notice", "kind": row.kind, "text": row.text})
    return json.dumps(rows, indent=2)
