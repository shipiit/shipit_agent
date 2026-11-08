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

import json
from typing import Any

from .sections import (
    _SECTION_RENDERERS,
    _render_chart,
)
from .styles import BASE_CSS
from .values import _color as _color
from .values import _esc
from .values import _pct as _pct

# ─────────────────────── section renderers ───────────────────────


# ─────────────────────── top-level ───────────────────────


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
