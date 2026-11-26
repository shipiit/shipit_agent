"""PDF loading and the metadata, page and text actions."""

from __future__ import annotations

import io
import urllib.error
from typing import Any

from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.open_url.safe_fetch import checked_address, safe_urlopen
from shipit_agent.tools.open_url.url_safety import URLNotAllowedError
from shipit_agent.tools.paths import resolve_in_roots

from .values import _coerce_str


class _PDFActions:
    """PDF loading and the metadata, page and text actions."""

    def _refusal(self, source: str) -> ToolOutput | None:
        """Why *source* may not be read at all: an internal URL, or a path outside the project."""
        if source.startswith(("http://", "https://")):
            if self.allow_private_hosts:
                return None
            try:
                checked_address(source)
            except URLNotAllowedError as exc:
                return ToolOutput(
                    text=f"Failed to fetch PDF from URL: {exc}",
                    metadata={"error": "url_fetch_failed", "message": str(exc), "source": source},
                )
            return None
        try:
            resolve_in_roots(source, self.root_dir.resolve(), self.extra_roots)
        except ValueError:
            return ToolOutput(
                text=f"PDF not read: {source} is outside the project ({self.root_dir}).",
                metadata={"error": "path_outside_project", "source": source},
            )
        return None

    def _load_source(self, source: str) -> io.BytesIO | ToolOutput:
        if source.startswith(("http://", "https://")):
            try:
                with safe_urlopen(source, timeout=self.timeout_seconds,
                                  allow_private=self.allow_private_hosts) as resp:
                    data = resp.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
                return ToolOutput(
                    text=f"Failed to fetch PDF from URL: {exc}",
                    metadata={
                        "error": "url_fetch_failed",
                        "message": str(exc),
                        "source": source,
                    },
                )
            return io.BytesIO(data)

        try:
            # A local PDF must be inside the project (or an added folder).
            path = resolve_in_roots(source, self.root_dir.resolve(), self.extra_roots)
        except ValueError:
            return ToolOutput(
                text=f"PDF not read: {source} is outside the project ({self.root_dir}).",
                metadata={"error": "path_outside_project", "source": source},
            )
        if not path.exists() or not path.is_file():
            return ToolOutput(
                text=f"PDF not found: {source}",
                metadata={"error": "file_not_found", "source": source},
            )
        try:
            return io.BytesIO(path.read_bytes())
        except OSError as exc:
            return ToolOutput(
                text=f"Failed to read PDF: {exc}",
                metadata={
                    "error": "file_read_failed",
                    "message": str(exc),
                    "source": source,
                },
            )

    def _action_metadata(
        self, reader: Any, total_pages: int, source: str
    ) -> ToolOutput:
        info = reader.metadata or {}
        # pypdf DocumentInformation behaves like a mapping; coerce to plain dict.
        try:
            items = dict(info)
        except Exception:
            items = {}

        def _g(key: str) -> Any:
            # pypdf keys are like "/Title" / "/Author"; expose both shapes.
            for k in (key, f"/{key}"):
                if k in items and items[k] is not None:
                    return items[k]
            attr = getattr(info, key.lower(), None)
            return attr

        md = {
            "title": _coerce_str(_g("Title")),
            "author": _coerce_str(_g("Author")),
            "subject": _coerce_str(_g("Subject")),
            "creator": _coerce_str(_g("Creator")),
            "producer": _coerce_str(_g("Producer")),
            "creation_date": _coerce_str(_g("CreationDate")),
            "modification_date": _coerce_str(_g("ModDate")),
            "page_count": total_pages,
            "source": source,
        }

        lines = [
            f"- title: {md['title']}",
            f"- author: {md['author']}",
            f"- subject: {md['subject']}",
            f"- creator: {md['creator']}",
            f"- producer: {md['producer']}",
            f"- creation_date: {md['creation_date']}",
            f"- modification_date: {md['modification_date']}",
            f"- page_count: {md['page_count']}",
        ]
        return ToolOutput(text="\n".join(lines), metadata=md)

    def _action_extract_pages(
        self, reader: Any, indices: list[int], source: str
    ) -> ToolOutput:
        pages_payload: list[dict[str, Any]] = []
        for idx in indices:
            try:
                text = reader.pages[idx].extract_text() or ""
            except Exception as exc:
                text = ""
                pages_payload.append(
                    {
                        "page": idx + 1,
                        "text": text,
                        "error": str(exc),
                    }
                )
                continue
            pages_payload.append({"page": idx + 1, "text": text})

        return ToolOutput(
            text=f"Extracted {len(pages_payload)} pages from {source}",
            metadata={
                "pages": pages_payload,
                "source": source,
                "page_count": len(pages_payload),
            },
        )

    def _action_extract_text(
        self,
        reader: Any,
        indices: list[int],
        source: str,
        max_chars: int,
        total_pages: int,
    ) -> ToolOutput:
        chunks: list[str] = []
        for idx in indices:
            try:
                text = reader.pages[idx].extract_text() or ""
            except Exception:
                text = ""
            if text:
                chunks.append(text)

        joined = "\n\n".join(chunks)
        truncated = False
        if max_chars and len(joined) > max_chars:
            joined = joined[:max_chars].rstrip() + "\n…(truncated)"
            truncated = True

        return ToolOutput(
            text=joined,
            metadata={
                "source": source,
                "pages_extracted": len(indices),
                "total_pages": total_pages,
                "truncated": truncated,
                "char_count": len(joined),
            },
        )
