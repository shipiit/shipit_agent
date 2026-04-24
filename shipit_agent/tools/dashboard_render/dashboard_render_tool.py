"""``render_dashboard`` tool — standalone HTML dashboards from a JSON spec.

Modelled on the Claude-Desktop "life vision" / "finance one-pager"
dashboards: metric cards, growth chart, timeline, trait cards, phase
stack, verdict. The tool returns a self-contained HTML document
(inline CSS, Chart.js via CDN only when a chart is present) and
writes the full HTML to ``ToolOutput.metadata["artifact"]["content"]``
so :class:`~shipit_agent.autopilot.ArtifactCollector` picks it up on
ingest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import DASHBOARD_RENDER_PROMPT
from .renderer import render_dashboard


class DashboardRenderTool:
    def __init__(
        self,
        *,
        name: str = "render_dashboard",
        description: str = (
            "Render a rich HTML dashboard (metrics, timeline, bars, "
            "cards, phases, chart, verdict) from a structured spec."
        ),
        prompt: str | None = None,
        workspace_root: str | Path = ".shipit_workspace/dashboards",
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or DASHBOARD_RENDER_PROMPT
        self.prompt_instructions = (
            "Use when the user asks for a visual dashboard, one-pager, life "
            "vision, finance breakdown, or any structured answer that benefits "
            "from cards + charts instead of paragraphs of prose."
        )
        self.workspace_root = Path(workspace_root)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Top-level dashboard heading.",
                        },
                        "subtitle": {
                            "type": "string",
                            "description": "Smaller caption under the title (context, date).",
                        },
                        "lang": {
                            "type": "string",
                            "description": (
                                "BCP-47 language tag for the <html> element. "
                                "Use 'hi' for Hindi-mixed content, 'en' otherwise."
                            ),
                        },
                        "sections": {
                            "type": "array",
                            "description": (
                                "Ordered dashboard sections. Each item must have "
                                "a 'type' key — see the prompt for supported types "
                                "(metrics, line_chart, bar_chart, bars, timeline, "
                                "cards, lifestyle_grid, phases, callout, verdict)."
                            ),
                        },
                        "export": {
                            "type": "boolean",
                            "description": "If true, also write the HTML to disk.",
                            "default": False,
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional export filename or relative path. "
                                "Defaults to a slug of 'title'."
                            ),
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional artifact name override.",
                        },
                    },
                    "required": ["title", "sections"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        title = str(kwargs.get("title") or "Dashboard")
        raw_sections = kwargs.get("sections") or []
        if isinstance(raw_sections, str):
            # Some LLMs hand us a JSON string instead of a list. Be forgiving.
            try:
                raw_sections = json.loads(raw_sections)
            except (json.JSONDecodeError, ValueError):
                raw_sections = []

        spec: dict[str, Any] = {
            "title": title,
            "subtitle": kwargs.get("subtitle") or "",
            "lang": kwargs.get("lang") or "en",
            "sections": list(raw_sections) if isinstance(raw_sections, list) else [],
        }
        html_doc = render_dashboard(spec)

        artifact_name = str(kwargs.get("name") or _slug(title) or "dashboard") + ".html"
        artifact: dict[str, Any] = {
            "artifact": True,
            "kind": "file",
            "name": artifact_name,
            "content": html_doc,
            "language": "html",
            "media_type": "text/html",
            "sections": len(spec["sections"]),
        }

        if kwargs.get("export"):
            root = Path(
                context.state.get("artifact_workspace_root", self.workspace_root)
            )
            root.mkdir(parents=True, exist_ok=True)
            rel = kwargs.get("path") or artifact_name
            export_path = (root / rel).resolve()
            # Guard against path traversal outside the workspace.
            try:
                export_path.relative_to(root.resolve())
            except ValueError:
                export_path = root / Path(rel).name
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(html_doc, encoding="utf-8")
            artifact["path"] = str(export_path)

        context.state.setdefault("artifacts", []).append(
            {
                "name": artifact_name,
                "content": html_doc,
                "media_type": "text/html",
            }
        )

        return ToolOutput(
            text=(
                f"Dashboard rendered: {artifact_name} "
                f"({len(spec['sections'])} sections, {len(html_doc):,} chars)."
            ),
            metadata=artifact,
        )


def _slug(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower())
    return cleaned.strip("-.")[:60]
