"""Helpers for Anthropic **citations** — attaching source documents with
citations enabled and parsing the model's citations back out of the response.

When a ``document`` content block is sent with ``{"citations": {"enabled":
True}}``, Claude grounds its answer in that document and emits ``citations`` on
the text blocks of its reply (each pointing back at a character / page / block
range in the source). This module provides:

* :func:`text_document` / :func:`pdf_document` / :func:`url_pdf_document` /
  :func:`content_document` — constructors for the ``document`` content block,
  matching the SDK's source-param shapes, and
* :func:`extract_citations` — pulls citation dicts out of a response's text
  blocks into a plain list suitable for ``LLMResponse.metadata["citations"]``.

All identifiers verified against ``anthropic`` 0.79.0
(``anthropic.types.document_block_param`` and its ``Source`` union:
``Base64PDFSourceParam`` / ``PlainTextSourceParam`` / ``ContentBlockSourceParam``
/ ``URLPDFSourceParam``; ``CitationsConfigParam`` = ``{"enabled": bool}``).
"""

from __future__ import annotations

from typing import Any


def _document(
    source: dict[str, Any],
    *,
    title: str | None,
    context: str | None,
    citations: bool,
) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "document", "source": source}
    if title is not None:
        block["title"] = title
    if context is not None:
        block["context"] = context
    if citations:
        block["citations"] = {"enabled": True}
    return block


def text_document(
    text: str,
    *,
    title: str | None = None,
    context: str | None = None,
    citations: bool = True,
) -> dict[str, Any]:
    """A plain-text ``document`` block (``source.type == "text"``).

    Citations are enabled by default — that is the whole point of the helper.
    """
    return _document(
        {"type": "text", "media_type": "text/plain", "data": text},
        title=title,
        context=context,
        citations=citations,
    )


def pdf_document(
    data_base64: str,
    *,
    title: str | None = None,
    context: str | None = None,
    citations: bool = True,
) -> dict[str, Any]:
    """A base64 PDF ``document`` block (``source.type == "base64"``)."""
    return _document(
        {"type": "base64", "media_type": "application/pdf", "data": data_base64},
        title=title,
        context=context,
        citations=citations,
    )


def url_pdf_document(
    url: str,
    *,
    title: str | None = None,
    context: str | None = None,
    citations: bool = True,
) -> dict[str, Any]:
    """A URL-sourced PDF ``document`` block (``source.type == "url"``)."""
    return _document(
        {"type": "url", "url": url},
        title=title,
        context=context,
        citations=citations,
    )


def content_document(
    content: Any,
    *,
    title: str | None = None,
    context: str | None = None,
    citations: bool = True,
) -> dict[str, Any]:
    """A ``document`` block built from content blocks (``source.type ==
    "content"``). ``content`` may be a string or a list of content-block dicts.
    """
    return _document(
        {"type": "content", "content": content},
        title=title,
        context=context,
        citations=citations,
    )


def extract_citations(content_blocks: Any) -> list[dict[str, Any]]:
    """Extract citation entries from a response's content blocks.

    Iterates text blocks, reads each block's ``citations`` (a list of location
    objects such as ``char_location`` / ``page_location`` /
    ``content_block_location``), and returns them as plain dicts. Defensive
    throughout: any block shape that doesn't look like a cited text block is
    skipped, so non-citation responses simply yield ``[]``.
    """
    out: list[dict[str, Any]] = []
    for block in content_blocks or []:
        try:
            if getattr(block, "type", None) != "text":
                continue
            cites = getattr(block, "citations", None)
            if not cites:
                continue
            for cite in cites:
                if isinstance(cite, dict):
                    out.append(dict(cite))
                elif hasattr(cite, "model_dump"):
                    out.append(cite.model_dump())
                elif hasattr(cite, "__dict__"):
                    out.append(
                        {k: v for k, v in vars(cite).items() if not k.startswith("_")}
                    )
        except Exception:
            # Never let an unexpected block shape break the main response path.
            continue
    return out
