"""Tests for the DashboardRenderTool + render_dashboard helpers.

Cover each section type renders, HTML escaping is tight, chart script
only shows up when a chart is present, disk export lands under the
workspace, the tool's artifact metadata is Autopilot-friendly, and
path-traversal in the ``path`` argument is neutralised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.autopilot import ArtifactCollector
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.dashboard_render import DashboardRenderTool, render_dashboard
from shipit_agent.tools.dashboard_render.renderer import _color, _pct


# ─────────────────────── renderer unit ───────────────────────


class TestRendererUnit:
    def test_empty_spec_produces_valid_document(self) -> None:
        html = render_dashboard({"title": "empty"})
        assert html.startswith("<!DOCTYPE html>")
        assert "<title>empty</title>" in html
        # No chart → no Chart.js script.
        assert "chart.umd" not in html

    def test_html_escapes_user_input(self) -> None:
        html = render_dashboard({
            "title": "<script>alert(1)</script>",
            "sections": [{
                "type": "metrics",
                "title": "KPIs",
                "items": [{"label": "<b>X</b>", "value": "Y</div>", "sub": "&amp;"}],
            }],
        })
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "Y&lt;/div&gt;" in html

    def test_color_allowlist_rejects_css_injection(self) -> None:
        # A hostile color string must not land in the style= attribute.
        assert _color("red;background:url(javascript:0)") == "#888888"
        assert _color("#1d9e75") == "#1d9e75"
        assert _color(None, fallback="#abcdef") == "#abcdef"

    def test_pct_clamps_to_unit_interval(self) -> None:
        assert _pct(150) == 100.0
        assert _pct(-10) == 0.0
        assert _pct("42") == 42.0
        assert _pct("junk") == 0.0

    def test_timeline_renders_each_item_with_badges(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{
                "type": "timeline",
                "title": "Love Timeline",
                "items": [
                    {"period": "Now", "head": "Start", "desc": "Prep.",
                     "dot_color": "#888888",
                     "tags": [{"text": "Prep", "color": "amber"}]},
                    {"period": "Next", "head": "Peak", "desc": "Connection.",
                     "dot_color": "#185fa5",
                     "tags": [{"text": "Peak", "color": "blue"}]},
                ],
            }],
        })
        # Count real <div> occurrences, not the CSS class name which
        # also appears in the embedded stylesheet.
        assert html.count('<div class="tl-row">') == 2
        assert "b-amber" in html and "b-blue" in html
        # Only one tl-line div — the last row never gets a trailing line.
        assert html.count('<div class="tl-line">') == 1

    def test_cards_with_dotted_trait_rows(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{
                "type": "cards",
                "title": "Partner",
                "columns": 2,
                "cards": [
                    {"title": "Appearance", "rows": [
                        {"strong": "Eyes:", "text": "Expressive.",
                         "dot_color": "#185fa5"},
                    ]},
                    {"title": "Personality", "rows": [
                        {"strong": "First:", "text": "Reserved.",
                         "dot_color": "#1d9e75"},
                    ]},
                ],
            }],
        })
        assert html.count('<div class="card-title">') == 2
        assert "<strong>Eyes:</strong>" in html
        assert "<strong>First:</strong>" in html

    def test_phases_use_caller_color_for_left_border(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{
                "type": "phases",
                "title": "Phases",
                "items": [
                    {"year": "2026", "sub": "Foundation", "items": "Ship.",
                     "color": "#ba7517"},
                ],
            }],
        })
        assert "border-left-color:#ba7517" in html

    def test_verdict_supports_inline_bold(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{
                "type": "verdict",
                "title": "Final",
                "text": "You are on a **self-made** path. <b>raw</b> should escape.",
            }],
        })
        assert "<strong>self-made</strong>" in html
        # A raw <b> tag in the source is still escaped.
        assert "<b>raw</b>" not in html
        assert "&lt;b&gt;raw&lt;/b&gt;" in html

    def test_lifestyle_and_bars_and_callout_smoke(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [
                {"type": "lifestyle_grid", "title": "Life",
                 "items": [{"icon": "🏠", "title": "Home", "desc": "Warsaw."}]},
                {"type": "bars", "title": "Mix",
                 "items": [{"label": "A", "pct": 72, "color": "#1d9e75"}]},
                {"type": "callout", "title": "Note",
                 "text": "Keep going."},
            ],
        })
        assert "🏠" in html
        # Width renders as "72.0%" because _pct normalises to float.
        assert "width:72.0%" in html
        assert '<div class="callout-head">' in html

    def test_unknown_section_types_are_skipped(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{"type": "never-heard-of-this", "title": "x"}],
        })
        # The section title WOULD have been rendered as a heading, but a
        # renderer for this type doesn't exist, so the whole block is skipped.
        assert 'sec-title">x</div>' not in html

    def test_chart_section_emits_canvas_and_chartjs(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [{
                "type": "line_chart",
                "title": "Growth",
                "labels": ["2026", "2027", "2028"],
                "values": [10, 20, 30],
                "color": "#185fa5",
            }],
        })
        assert "<canvas" in html
        assert 'cdn.jsdelivr.net/npm/chart.js' in html
        # The chart config JSON is embedded; labels round-trip.
        assert '"2026"' in html and '"2027"' in html

    def test_bar_chart_works_alongside_line_chart(self) -> None:
        html = render_dashboard({
            "title": "t",
            "sections": [
                {"type": "line_chart", "title": "A", "labels": ["x"], "values": [1]},
                {"type": "bar_chart",  "title": "B", "labels": ["y"], "values": [2]},
            ],
        })
        # Two canvases, one script tag with both inits.
        assert html.count("<canvas") == 2
        assert html.count('new Chart') == 2


# ─────────────────────── tool behavior ───────────────────────


class TestDashboardRenderTool:
    def _run(self, tool: DashboardRenderTool, **kwargs: Any) -> Any:
        ctx = ToolContext(prompt="render")
        return tool.run(ctx, **kwargs)

    def test_happy_path_returns_html_artifact(self, tmp_path: Path) -> None:
        tool = DashboardRenderTool(workspace_root=tmp_path)
        out = self._run(
            tool,
            title="Rahul — Life Vision",
            subtitle="April 2026",
            lang="hi",
            sections=[
                {"type": "metrics", "title": "Snapshot", "columns": 4,
                 "items": [{"label": "Age", "value": "30"}]},
                {"type": "verdict", "title": "Verdict", "text": "Keep going."},
            ],
        )
        assert "artifact" in out.metadata
        assert out.metadata["artifact"] is True
        assert out.metadata["kind"] == "file"
        assert out.metadata["media_type"] == "text/html"
        assert out.metadata["name"].endswith(".html")
        assert "<!DOCTYPE html>" in out.metadata["content"]
        assert "Life Vision" in out.metadata["content"]

    def test_sections_accept_json_string_fallback(self, tmp_path: Path) -> None:
        """Some LLMs hand us the sections list as a JSON string — the
        tool should parse it instead of silently dropping the data."""
        tool = DashboardRenderTool(workspace_root=tmp_path)
        as_string = json.dumps([
            {"type": "callout", "title": "Note", "text": "ok"},
        ])
        out = self._run(tool, title="t", sections=as_string)
        assert out.metadata["sections"] == 1
        assert "callout-body" in out.metadata["content"]

    def test_export_writes_under_workspace(self, tmp_path: Path) -> None:
        tool = DashboardRenderTool(workspace_root=tmp_path)
        out = self._run(
            tool,
            title="export-me",
            sections=[{"type": "callout", "title": "x", "text": "y"}],
            export=True,
        )
        exported = Path(out.metadata["path"])
        assert exported.exists()
        assert exported.is_relative_to(tmp_path)
        assert exported.suffix == ".html"
        assert "<!DOCTYPE html>" in exported.read_text()

    def test_export_path_traversal_is_neutralised(self, tmp_path: Path) -> None:
        """An LLM that hands us ``../../../etc/passwd`` should not get
        the dashboard written outside the workspace."""
        tool = DashboardRenderTool(workspace_root=tmp_path)
        out = self._run(
            tool,
            title="t", sections=[{"type": "callout", "title": "x", "text": "y"}],
            export=True, path="../../../etc/passwd",
        )
        exported = Path(out.metadata["path"])
        # Export stayed inside the workspace.
        assert exported.is_relative_to(tmp_path.resolve())
        # Filename is the basename only.
        assert exported.name == "passwd"

    def test_schema_round_trips(self) -> None:
        tool = DashboardRenderTool()
        schema = tool.schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "render_dashboard"
        assert "sections" in schema["function"]["parameters"]["properties"]

    def test_workspace_root_override_via_context_state(self, tmp_path: Path) -> None:
        """A caller (chat runtime, autopilot) can redirect exports per-call
        by stuffing ``artifact_workspace_root`` into :attr:`ToolContext.state`."""
        tool = DashboardRenderTool(workspace_root=tmp_path / "default")
        alt = tmp_path / "caller-override"
        ctx = ToolContext(prompt="x", state={"artifact_workspace_root": str(alt)})
        out = tool.run(
            ctx, title="alt",
            sections=[{"type": "callout", "title": "x", "text": "y"}],
            export=True,
        )
        exported = Path(out.metadata["path"])
        assert exported.is_relative_to(alt.resolve())


# ─────────────────────── autopilot integration ───────────────────────


class TestAutopilotArtifactIngest:
    def test_tool_metadata_is_ingestable_by_artifact_collector(self, tmp_path: Path) -> None:
        """The tool's metadata shape matches what ArtifactCollector expects
        (``artifact=True`` + ``kind`` / ``name`` / ``content``) so an
        Autopilot run with this tool naturally surfaces the HTML as an
        artifact without any glue code."""
        tool = DashboardRenderTool(workspace_root=tmp_path)
        ctx = ToolContext(prompt="x")
        out = tool.run(
            ctx, title="Pipeline",
            sections=[{"type": "callout", "title": "x", "text": "y"}],
        )

        collector = ArtifactCollector()
        added = collector.ingest_tool_metadata(out.metadata, iteration=1)
        assert len(added) == 1
        artifact = added[0]
        assert artifact.kind == "file"
        assert artifact.name.endswith(".html")
        assert "<!DOCTYPE html>" in artifact.content


# ─────────────────────── full-fledged "life vision" dashboard ───────────────────────


def test_life_vision_dashboard_full_spec(tmp_path: Path) -> None:
    """Exercise every section type together in one realistic spec —
    proves the renderer composes cleanly without inter-section bleed
    (chart script at the end, timeline badges inside the tl-wrap, etc).
    """
    tool = DashboardRenderTool(workspace_root=tmp_path)
    out = tool.run(
        ToolContext(prompt="life"),
        title="Rahul — Complete Life Vision 2026–2035",
        subtitle="Kundli + Hast Rekha · April 2026",
        lang="hi",
        sections=[
            {"type": "metrics", "title": "Snapshot", "columns": 4, "items": [
                {"label": "Age", "value": "30", "sub": "Best phase ahead"},
                {"label": "Dasha", "value": "शुक्र", "sub": "until 2043"},
                {"label": "Ventures", "value": "4", "sub": "ShipIt primary"},
                {"label": "Saadhesati", "value": "Peak", "sub": "ends June 2027",
                 "color": "#ba7517"},
            ]},
            {"type": "line_chart", "title": "Income growth 2026–2035",
             "labels": [str(y) for y in range(2026, 2036)],
             "values": [20, 35, 55, 70, 85, 95, 110, 140, 165, 190],
             "color": "#185fa5"},
            {"type": "bars", "title": "Income sources",
             "items": [
                 {"label": "Enterprise licensing", "pct": 88, "color": "#185fa5"},
                 {"label": "SaaS subscriptions",   "pct": 75, "color": "#1d9e75"},
                 {"label": "Consulting",           "pct": 38, "color": "#888888"},
             ]},
            {"type": "timeline", "title": "Love life timeline", "items": [
                {"period": "Now", "head": "Prep", "desc": "Inner work.",
                 "dot_color": "#888888", "tags": [{"text": "Prep", "color": "amber"}]},
                {"period": "Jun–Jul 2026", "head": "Peak window",
                 "desc": "Significant connection.",
                 "dot_color": "#185fa5",
                 "tags": [{"text": "Peak", "color": "blue"},
                          {"text": "She arrives", "color": "blue"}]},
            ]},
            {"type": "cards", "title": "Partner portrait", "columns": 2, "cards": [
                {"title": "Physical", "rows": [
                    {"strong": "Eyes:", "text": "Expressive.",
                     "dot_color": "#185fa5"},
                    {"strong": "Height:", "text": "Medium.",
                     "dot_color": "#185fa5"},
                ]},
                {"title": "Personality", "rows": [
                    {"strong": "First:", "text": "Reserved.",
                     "dot_color": "#1d9e75"},
                    {"strong": "Love style:", "text": "Acts of service.",
                     "dot_color": "#1d9e75"},
                ]},
            ]},
            {"type": "lifestyle_grid", "title": "Future lifestyle", "items": [
                {"icon": "🏠", "title": "Housing — 2027",
                 "desc": "Better Warsaw apartment."},
                {"icon": "🚗", "title": "Car — 2027–28",
                 "desc": "Quality, utility-focused."},
                {"icon": "💍", "title": "Marriage",
                 "desc": "Meaningful ceremony."},
            ]},
            {"type": "phases", "title": "Life phases", "items": [
                {"year": "2026 — Foundation", "sub": "Venus–Venus",
                 "items": "ShipIt PH · first enterprise deal · income 3–5x",
                 "color": "#ba7517"},
                {"year": "2030–33 — Breakthrough", "sub": "Venus–Rahu",
                 "items": "Major funding · acquisition offer possible",
                 "color": "#d85a30"},
            ]},
            {"type": "verdict", "title": "Final verdict",
             "text": "Tumhara **best chapter** abhi likhna baaki hai."},
        ],
        export=True,
    )

    html = out.metadata["content"]
    # All eight sections rendered.
    assert html.count('class="sec"') == 8
    # Chart.js script is loaded exactly once, even with multiple charts possible.
    assert html.count('src="https://cdn.jsdelivr.net/npm/chart.js') == 1
    # Escaped text from the verdict arrived as bold.
    assert "<strong>best chapter</strong>" in html
    # Hindi text survived.
    assert "शुक्र" in html
    # Exported file exists and matches.
    exported = Path(out.metadata["path"])
    assert exported.exists()
    assert exported.read_text() == html
