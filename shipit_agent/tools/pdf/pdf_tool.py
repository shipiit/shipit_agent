"""``pdf`` tool — extract text, per-page content, and metadata from PDFs.

Supports local paths and ``http(s)://`` URLs. ``pypdf`` is imported lazily so
that the base install stays slim; if the dependency is missing the tool
returns a friendly ``pypdf_missing`` error with an install hint.

Used for contracts, research papers, reports, and any document ingestion
flow where the agent needs structured text rather than a screenshot.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .actions import _PDFActions
from .prompt import PDF_PROMPT

_VALID_ACTIONS = {"extract_text", "extract_pages", "metadata", "page_count"}


def parse_pages(spec: str | None, total_pages: int | None = None) -> list[int]:
    """Parse a page-range spec into 0-indexed page numbers.

    ``"1-3,5,7-9"`` → ``[0, 1, 2, 4, 6, 7, 8]``. Whitespace-tolerant.
    Empty / ``None`` → ``[]`` (meaning "all pages" to the caller).
    Out-of-range pages are silently dropped when ``total_pages`` is supplied.
    """
    if spec is None:
        return []
    cleaned = str(spec).strip()
    if not cleaned:
        return []

    result: list[int] = []
    seen: set[int] = set()
    for raw_part in cleaned.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, _, hi_s = part.partition("-")
            try:
                lo = int(lo_s.strip())
                hi = int(hi_s.strip())
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            for one_based in range(lo, hi + 1):
                idx = one_based - 1
                if idx < 0:
                    continue
                if total_pages is not None and idx >= total_pages:
                    continue
                if idx not in seen:
                    seen.add(idx)
                    result.append(idx)
        else:
            try:
                idx = int(part) - 1
            except ValueError:
                continue
            if idx < 0:
                continue
            if total_pages is not None and idx >= total_pages:
                continue
            if idx not in seen:
                seen.add(idx)
                result.append(idx)
    return result


class PDFTool(_PDFActions):
    """The ``pdf`` tool: extract text, per-page content, or metadata from a PDF file (local or URL).
    """
    def __init__(
        self,
        *,
        name: str = "pdf",
        description: str = (
            "Extract text, per-page content, or metadata from a PDF file "
            "(local or URL)."
        ),
        max_chars_default: int = 50_000,
        timeout_seconds: int = 30,
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.max_chars_default = int(max_chars_default)
        self.timeout_seconds = int(timeout_seconds)
        self.prompt = prompt or PDF_PROMPT
        self.prompt_instructions = (
            "Use to extract text or metadata from a PDF — contracts, research "
            "papers, reports, invoices. Supports local paths and http(s) URLs."
        )

    # ──────────────────────────── schema ────────────────────────────

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": sorted(_VALID_ACTIONS),
                            "description": (
                                "What to do with the PDF: extract_text, "
                                "extract_pages, metadata, or page_count."
                            ),
                        },
                        "source": {
                            "type": "string",
                            "description": (
                                "Local file path or http(s):// URL to the PDF."
                            ),
                        },
                        "pages": {
                            "type": "string",
                            "description": (
                                "Page range, e.g. '1-3,5,7-9' or '1,3,5'. "
                                "Empty → all pages. Out-of-range → clamped."
                            ),
                        },
                        "max_chars": {
                            "type": "number",
                            "description": (
                                "Max characters for extract_text (default "
                                f"{self.max_chars_default}). Output is "
                                "truncated with a marker when hit."
                            ),
                        },
                    },
                    "required": ["action", "source"],
                },
            },
        }

    # ──────────────────────────── run ───────────────────────────────

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        action = str(kwargs.get("action") or "").strip()
        source = str(kwargs.get("source") or "").strip()
        pages_spec = kwargs.get("pages")
        max_chars_kw = kwargs.get("max_chars")

        if action not in _VALID_ACTIONS:
            return ToolOutput(
                text=f"Unknown action: {action!r}",
                metadata={
                    "error": "unknown_action",
                    "valid_actions": sorted(_VALID_ACTIONS),
                },
            )
        if not source:
            return ToolOutput(
                text="No PDF source provided.",
                metadata={"error": "missing_source"},
            )

        # Lazy import — keeps the base install pypdf-free.
        try:
            import pypdf  # type: ignore[import-not-found]
        except ImportError:
            return ToolOutput(
                text=(
                    "pypdf is not installed. "
                    "Install with: pip install 'shipit-agent[pdf]'"
                ),
                metadata={
                    "error": "pypdf_missing",
                    "install": "pip install 'shipit-agent[pdf]'",
                },
            )

        # Load bytes.
        load_result = self._load_source(source)
        if isinstance(load_result, ToolOutput):
            return load_result
        stream = load_result

        # Parse.
        try:
            reader = pypdf.PdfReader(stream)
        except Exception as exc:  # pypdf raises many exception types
            return ToolOutput(
                text=f"Failed to parse PDF: {exc}",
                metadata={
                    "error": "pdf_parse_error",
                    "message": str(exc),
                    "source": source,
                },
            )

        total_pages = len(reader.pages)

        if action == "page_count":
            return ToolOutput(
                text=f"{total_pages} pages.",
                metadata={"page_count": total_pages, "source": source},
            )

        if action == "metadata":
            return self._action_metadata(reader, total_pages, source)

        # For extract_text / extract_pages, resolve page indices.
        selected = parse_pages(pages_spec if isinstance(pages_spec, str) else None, total_pages)
        if not selected:
            selected = list(range(total_pages))

        if action == "extract_pages":
            return self._action_extract_pages(reader, selected, source)

        # extract_text
        try:
            max_chars = int(max_chars_kw) if max_chars_kw is not None else self.max_chars_default
        except (TypeError, ValueError):
            max_chars = self.max_chars_default
        if max_chars < 0:
            max_chars = self.max_chars_default
        return self._action_extract_text(reader, selected, source, max_chars, total_pages)

    # ──────────────────────────── helpers ───────────────────────────
