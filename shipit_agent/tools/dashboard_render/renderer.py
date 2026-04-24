"""HTML rendering for the dashboard tool.

The renderer takes a plain-Python dashboard spec (see :func:`render_dashboard`)
and returns a single self-contained HTML string. Chart.js is only loaded
(via CDN) when at least one chart section exists, so simple dashboards
stay offline-friendly.

All user-supplied strings are HTML-escaped. Colors go through a small
allow-list / hex check — arbitrary CSS in ``style=`` attributes would
be an XSS vector.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from .styles import BASE_CSS


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_BADGE_VARIANTS = {"blue", "green", "amber", "purple", "gray", "red"}


def _esc(text: Any) -> str:
    """HTML-escape anything. ``None`` renders as empty string so callers
    don't have to guard every optional field."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _color(c: str | None, fallback: str = "#888888") -> str:
    """Return ``c`` if it's a safe hex color, otherwise ``fallback``.

    Belt-and-braces: we interpolate colors into inline ``style=``, and
    an attacker who controlled the spec could otherwise inject
    ``;background:url(javascript:…)``. Rejecting anything that isn't a
    hex triple keeps the XSS surface at zero.
    """
    if c and _HEX_COLOR.match(c):
        return c
    return fallback


def _pct(v: Any, default: float = 0.0) -> float:
    """Clamp any numeric-ish input into [0, 100]."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, n))


# ─────────────────────── section renderers ───────────────────────


def _render_metrics(section: dict[str, Any]) -> str:
    columns = int(section.get("columns") or 4)
    grid_class = {2: "g2", 3: "g3", 4: "g4"}.get(columns, "g4")
    cells: list[str] = []
    for item in section.get("items", []) or []:
        value = _esc(item.get("value"))
        value_cls = (
            "metric-value small"
            if len(str(item.get("value") or "")) > 6
            else "metric-value"
        )
        value_color = f"color:{_color(item.get('color'))}" if item.get("color") else ""
        cells.append(
            f'<div class="metric">'
            f'<div class="metric-label">{_esc(item.get("label"))}</div>'
            f'<div class="{value_cls}" style="{value_color}">{value}</div>'
            f'<div class="metric-sub">{_esc(item.get("sub"))}</div>'
            f'</div>'
        )
    return f'<div class="{grid_class}">{"".join(cells)}</div>'


def _render_bars(section: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in section.get("items", []) or []:
        pct = _pct(item.get("pct"))
        color = _color(item.get("color"), fallback="#185fa5")
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-lbl">{_esc(item.get("label"))}</div>'
            f'<div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>'
            f'<div class="bar-pct">{pct:g}%</div>'
            f'</div>'
        )
    return "".join(rows)


def _render_badges(tags: list[dict[str, Any]] | None) -> str:
    if not tags:
        return ""
    out: list[str] = []
    for tag in tags:
        variant = (tag.get("color") or "gray").lower()
        cls = f"b-{variant}" if variant in _BADGE_VARIANTS else "b-gray"
        out.append(f'<span class="badge {cls}">{_esc(tag.get("text"))}</span>')
    return f'<div class="tl-tags">{"".join(out)}</div>'


def _render_timeline(section: dict[str, Any]) -> str:
    rows: list[str] = []
    items = section.get("items") or []
    for idx, item in enumerate(items):
        dot = _color(item.get("dot_color"), fallback="#185fa5")
        line = "" if idx == len(items) - 1 else '<div class="tl-line"></div>'
        rows.append(
            f'<div class="tl-row">'
            f'<div class="tl-dot" style="background:{dot}"></div>{line}'
            f'<div class="tl-period">{_esc(item.get("period"))}</div>'
            f'<div class="tl-head">{_esc(item.get("head"))}</div>'
            f'<div class="tl-desc">{_esc(item.get("desc"))}</div>'
            f'{_render_badges(item.get("tags"))}'
            f'</div>'
        )
    return f'<div class="tl-wrap">{"".join(rows)}</div>'


def _render_cards(section: dict[str, Any]) -> str:
    columns = int(section.get("columns") or 2)
    grid_class = {2: "g2", 3: "g3"}.get(columns, "g2")
    cards: list[str] = []
    for card in section.get("cards", []) or []:
        rows: list[str] = []
        for row in card.get("rows", []) or []:
            dot = _color(row.get("dot_color"), fallback="#185fa5")
            strong = _esc(row.get("strong"))
            text = _esc(row.get("text"))
            label_html = f"<strong>{strong}</strong> " if strong else ""
            rows.append(
                f'<div class="trait-row">'
                f'<div class="trait-dot" style="background:{dot}"></div>'
                f'<div class="trait-text">{label_html}{text}</div>'
                f"</div>"
            )
        cards.append(
            f'<div class="card">'
            f'<div class="card-title">{_esc(card.get("title"))}</div>'
            f'{"".join(rows)}'
            f'</div>'
        )
    return f'<div class="{grid_class}">{"".join(cards)}</div>'


def _render_lifestyle(section: dict[str, Any]) -> str:
    cells: list[str] = []
    for item in section.get("items", []) or []:
        icon = _esc(item.get("icon"))
        title = _esc(item.get("title"))
        header = f"{icon} {title}".strip()
        cells.append(
            f'<div class="lifestyle-item">'
            f'<div class="lifestyle-title">{header}</div>'
            f'<div class="lifestyle-desc">{_esc(item.get("desc"))}</div>'
            f'</div>'
        )
    return f'<div class="lifestyle-grid">{"".join(cells)}</div>'


def _render_phases(section: dict[str, Any]) -> str:
    rows: list[str] = []
    for phase in section.get("items", []) or []:
        border = _color(phase.get("color"), fallback="#888888")
        rows.append(
            f'<div class="phase-card" style="border-left-color:{border}">'
            f'<div class="phase-year">{_esc(phase.get("year"))}</div>'
            f'<div class="phase-sub">{_esc(phase.get("sub"))}</div>'
            f'<div class="phase-items">{_esc(phase.get("items"))}</div>'
            f'</div>'
        )
    return "".join(rows)


def _render_verdict(section: dict[str, Any]) -> str:
    """Verdict text allows light bold (**foo**) because astrology/review
    dashboards lean on emphasis. No other markdown."""
    raw = str(section.get("text") or "")
    escaped = html.escape(raw, quote=True)
    bolded = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return (
        f'<div class="verdict-box">'
        f'<div class="verdict-title">{_esc(section.get("heading") or section.get("title"))}</div>'
        f'<div class="verdict-text">{bolded}</div>'
        f'</div>'
    )


def _render_callout(section: dict[str, Any]) -> str:
    return (
        f'<div class="callout">'
        f'<div class="callout-head">{_esc(section.get("heading") or section.get("title"))}</div>'
        f'<div class="callout-body">{_esc(section.get("text"))}</div>'
        f'</div>'
    )


def _render_chart(section: dict[str, Any], chart_id: str) -> str:
    """Emit only the canvas — the ``<script>`` block is added once at
    the end of the document with aggregated chart data."""
    labels = section.get("labels") or []
    summary = section.get("aria") or (
        f"Series from {labels[0] if labels else 'start'} to {labels[-1] if labels else 'end'}."
    )
    return (
        f'<div class="chart-wrap">'
        f'<canvas id="{chart_id}" role="img" aria-label="{_esc(summary)}">{_esc(summary)}</canvas>'
        f"</div>"
    )


# ─────────────────────── top-level ───────────────────────


_SECTION_RENDERERS = {
    "metrics": _render_metrics,
    "bars": _render_bars,
    "timeline": _render_timeline,
    "cards": _render_cards,
    "lifestyle_grid": _render_lifestyle,
    "phases": _render_phases,
    "verdict": _render_verdict,
    "callout": _render_callout,
}


def _chart_config(section: dict[str, Any]) -> dict[str, Any]:
    kind = (section.get("chart") or "line").lower()
    if kind not in {"line", "bar"}:
        kind = "line"
    color = _color(section.get("color"), fallback="#185fa5")
    labels = [str(x) for x in (section.get("labels") or [])]
    data = [float(x) for x in (section.get("values") or [0] * len(labels))]
    return {
        "type": kind,
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": str(section.get("series_label") or "value"),
                    "data": data,
                    "borderColor": color,
                    "backgroundColor": color + "14",
                    "borderWidth": 2,
                    "pointBackgroundColor": color,
                    "pointRadius": 4,
                    "fill": True,
                    "tension": 0.35,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": False}},
            "scales": {
                "x": {
                    "grid": {"color": "rgba(136,135,128,0.15)"},
                    "ticks": {"color": "#888", "font": {"size": 11}},
                },
                "y": {
                    "beginAtZero": True,
                    "grid": {"color": "rgba(136,135,128,0.15)"},
                    "ticks": {"color": "#888", "font": {"size": 11}},
                },
            },
        },
    }


def render_dashboard(spec: dict[str, Any]) -> str:
    """Render a dashboard spec to a standalone HTML document.

    The spec shape is documented on the tool itself; unknown section
    types are skipped silently so callers can add experimental sections
    without breaking older renderers.
    """
    title = _esc(spec.get("title") or "Dashboard")
    subtitle = _esc(spec.get("subtitle"))
    lang = _esc(spec.get("lang") or "en") or "en"

    body_parts: list[str] = [f"<h1>{title}</h1>"]
    if subtitle:
        body_parts.append(f'<div class="sub">{subtitle}</div>')

    chart_configs: list[tuple[str, dict[str, Any]]] = []
    for i, section in enumerate(spec.get("sections") or []):
        stype = (section.get("type") or "").lower()
        sec_title = _esc(section.get("title"))
        header = f'<div class="sec-title">{sec_title}</div>' if sec_title else ""

        if stype in ("line_chart", "bar_chart", "chart"):
            chart_id = f"chart_{i}"
            chart_configs.append((chart_id, _chart_config(section)))
            body_parts.append(
                f'<div class="sec">{header}{_render_chart(section, chart_id)}</div>'
            )
            continue

        renderer = _SECTION_RENDERERS.get(stype)
        if renderer is None:
            continue
        inner = renderer(section)
        body_parts.append(f'<div class="sec">{header}{inner}</div>')

    script = ""
    if chart_configs:
        inits = "".join(
            f"var c{i}=document.getElementById({json.dumps(cid)});"
            f"if(c{i}&&window.Chart){{new Chart(c{i},{json.dumps(cfg)});}}"
            for i, (cid, cfg) in enumerate(chart_configs)
        )
        script = (
            '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
            f"<script>{inits}</script>"
        )

    return (
        f'<!DOCTYPE html><html lang="{lang}"><head>'
        f'<meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f'<title>{title}</title>'
        f'<style>{BASE_CSS}</style>'
        f'</head><body>'
        f'{"".join(body_parts)}'
        f'{script}'
        f'</body></html>'
    )
