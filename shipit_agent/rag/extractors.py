"""File → text extractors.

``TXT`` and ``Markdown`` are supported with zero dependencies. ``PDF``,
``DOCX``, and ``HTML`` extraction requires optional libraries that are
imported lazily. Missing libraries raise :class:`RAGDependencyError`
with a clear install hint.
"""

from __future__ import annotations

import os
from typing import Callable


class RAGDependencyError(RuntimeError):
    """Raised when an optional RAG dependency is missing."""


class RAGIngestError(RuntimeError):
    """Raised when a file cannot be read or parsed."""

    def __init__(self, path: str, cause: Exception) -> None:
        super().__init__(f"Failed to ingest {path!r}: {cause}")
        self.path = path
        self.cause = cause


_Extractor = Callable[[str], str]


def _read_plaintext(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _read_pdf(path: str) -> str:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RAGDependencyError("PDF extraction requires `pip install pypdf`") from exc
    reader = pypdf.PdfReader(path)
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - defensive
            continue
    return "\n\n".join(p for p in parts if p.strip())


def _read_docx(path: str) -> str:
    try:
        import docx  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RAGDependencyError(
            "DOCX extraction requires `pip install python-docx`"
        ) from exc
    document = docx.Document(path)
    return "\n".join(p.text for p in document.paragraphs if p.text)


def _read_html(path: str) -> str:
    try:
        from html.parser import HTMLParser
    except ImportError as exc:  # pragma: no cover - stdlib
        raise RAGDependencyError("HTML parser missing") from exc

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            if data.strip():
                self.parts.append(data.strip())

    parser = _Stripper()
    parser.feed(_read_plaintext(path))
    return "\n".join(parser.parts)


_EXTRACTORS: dict[str, _Extractor] = {
    ".txt": _read_plaintext,
    ".md": _read_plaintext,
    ".markdown": _read_plaintext,
    ".log": _read_plaintext,
    ".csv": _read_plaintext,
    ".json": _read_plaintext,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".html": _read_html,
    ".htm": _read_html,
}


class TextExtractor:
    """Extract plain text from a file path.

    Usage::

        extractor = TextExtractor()
        text = extractor.extract("docs/manual.pdf")
    """

    def extract(self, path: str) -> str:
        if not os.path.exists(path):
            raise RAGIngestError(path, FileNotFoundError(path))
        ext = os.path.splitext(path)[1].lower()
        extractor = _EXTRACTORS.get(ext)
        if extractor is None:
            # Default: try to read as UTF-8 text.
            extractor = _read_plaintext
        try:
            return extractor(path)
        except (RAGDependencyError, RAGIngestError):
            raise
        except Exception as exc:
            raise RAGIngestError(path, exc) from exc

    @staticmethod
    def supported_extensions() -> list[str]:
        return sorted(_EXTRACTORS.keys())
