"""Advanced file reading — turn office/web documents into clean Markdown.

``read_file`` uses this so a ``.docx``, ``.xlsx``, ``.pptx``, ``.html``, or
``.csv`` comes back as readable text instead of decoded-binary soup:

    from shipit_agent.tools.file_extract import extract_file
    markdown, backend = extract_file(Path("report.docx"))   # or None if unsupported

Extractors live in ``extractors`` (CSV built in on stdlib; DOCX/XLSX/PPTX/PDF
gated on their parsing libraries; HTML via markdownify with a stdlib fallback).
Each is availability-gated, so a format degrades gracefully to plain text when
its dependency isn't installed.
"""

from .extractors import (
    CsvExtractor,
    DocxExtractor,
    Extractor,
    HtmlExtractor,
    PdfExtractor,
    PptxExtractor,
    XlsxExtractor,
    available_suffixes,
    extract_file,
    extractor_for,
    register_extractor,
    supported_suffixes,
)

__all__ = [
    "CsvExtractor",
    "DocxExtractor",
    "Extractor",
    "HtmlExtractor",
    "PdfExtractor",
    "PptxExtractor",
    "XlsxExtractor",
    "available_suffixes",
    "extract_file",
    "extractor_for",
    "register_extractor",
    "supported_suffixes",
]
