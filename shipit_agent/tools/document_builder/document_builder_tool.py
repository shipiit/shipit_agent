"""`build_document` — polished PDF / Excel / Word / PowerPoint / HTML output.

The agent structures content once (title + sections, or sheets for Excel)
and picks a `kind`; styling — typography, accent colors, table zebra rows,
frozen header panes — is applied by the renderers so every document looks
finished, not generated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, ClassVar

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import DOCUMENT_BUILDER_PROMPT
from .renderers import render_docx, render_html, render_pdf, render_pptx, render_xlsx

_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "heading": {"type": "string"},
        "body": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "table": {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array"}},
            },
        },
    },
}


class DocumentBuilderTool:
    KINDS: ClassVar[dict[str, tuple[str, Callable[..., None]]]] = {
        "pdf": (".pdf", render_pdf),
        "xlsx": (".xlsx", render_xlsx),
        "docx": (".docx", render_docx),
        "pptx": (".pptx", render_pptx),
        "html": (".html", render_html),
    }

    def __init__(
        self,
        *,
        name: str = "build_document",
        description: str = (
            "Create a polished PDF report, Excel workbook, Word document, "
            "PowerPoint deck, or styled HTML page from structured content."
        ),
        prompt: str | None = None,
        workspace_root: str | Path = ".shipit_workspace/documents",
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or DOCUMENT_BUILDER_PROMPT
        self.prompt_instructions = (
            "Use this whenever the user wants a shareable deliverable — a "
            "report, spreadsheet, deck, or doc — rather than chat text."
        )
        self.workspace_root = Path(workspace_root)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": sorted(self.KINDS),
                            "description": "Output format",
                        },
                        "title": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": _SECTION_SCHEMA,
                            "description": (
                                "Document content (pdf/docx/pptx/html). For "
                                "pptx each section is one slide."
                            ),
                        },
                        "sheets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "headers": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "rows": {
                                        "type": "array",
                                        "items": {"type": "array"},
                                    },
                                },
                            },
                            "description": (
                                "Workbook content (xlsx only). Cell strings "
                                "starting with '=' become live formulas."
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional output path; defaults to the "
                                "workspace with a name derived from title."
                            ),
                        },
                    },
                    "required": ["kind", "title"],
                },
            },
        }

    def _output_path(self, kind: str, title: str, override: str | None) -> Path:
        suffix = self.KINDS[kind][0]
        if override:
            path = Path(override).expanduser()
            if path.suffix.lower() != suffix:
                path = path.with_suffix(suffix)
        else:
            slug = "".join(
                ch if ch.isalnum() or ch in "-_ " else "" for ch in title
            ).strip().replace(" ", "_").lower() or "document"
            path = self.workspace_root / f"{slug}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        kind = str(kwargs.get("kind", "")).lower()
        if kind not in self.KINDS:
            return ToolOutput(
                text=f"Unknown kind '{kind}'. Choose one of: {', '.join(sorted(self.KINDS))}.",
                metadata={"ok": False},
            )
        title = str(kwargs.get("title", "Document"))
        path = self._output_path(kind, title, kwargs.get("path"))
        renderer = self.KINDS[kind][1]
        content: Any = (
            kwargs.get("sheets") or []
            if kind == "xlsx"
            else kwargs.get("sections") or []
        )
        try:
            renderer(title, content, path)
        except ImportError as err:
            return ToolOutput(text=str(err), metadata={"ok": False, "kind": kind})
        except Exception as err:  # malformed content, disk errors, …
            return ToolOutput(
                text=f"Failed to build {kind}: {err}",
                metadata={"ok": False, "kind": kind, "error": str(err)},
            )
        size = path.stat().st_size
        return ToolOutput(
            text=f"Created {kind.upper()} '{title}' → {path} ({size:,} bytes)",
            metadata={
                "ok": True,
                "kind": kind,
                "path": str(path.resolve()),
                "bytes": size,
            },
        )
