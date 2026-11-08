"""One HTML renderer per dashboard section type."""

from __future__ import annotations

import html
import re
from typing import Any

from .values import _BADGE_VARIANTS, _color, _esc, _pct


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

