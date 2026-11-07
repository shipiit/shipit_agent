"""Turning a fetched HTML page into readable Markdown-ish text."""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


class _TextExtractor(HTMLParser):
    """Extract the main content of a page as readable markdown.

    Uses a real parser (not a regex tag filter) so malformed or nested
    ``<script>`` tags can't slip executable text into the output (clears
    CodeQL ``py/bad-tag-filter``). Unlike a flat tag-strip, this preserves
    structure — headings become ``#``, list items ``-``, paragraphs are
    separated by blank lines — and drops chrome (nav, header, footer, aside,
    forms) so the model reads the article, not the site furniture.
    """

    _SKIP = {
        "script", "style", "head", "noscript", "template", "svg",
        # site chrome — rarely the answer, always context cost
        "nav", "header", "footer", "aside", "form", "button", "iframe",
    }
    _BLOCK = {"p", "div", "section", "article", "br", "tr", "blockquote", "pre"}
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pending_prefix = ""

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._HEADINGS:
            self._parts.append("\n\n")
            self._pending_prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self._parts.append("\n")
            self._pending_prefix = "- "
        elif tag in self._BLOCK:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        if self._pending_prefix:
            self._parts.append(self._pending_prefix)
            self._pending_prefix = ""
        self._parts.append(data)

    def markdown(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of blank lines and trailing spaces into tidy markdown.
        lines = [re.sub(r"[ \t]+", " ", ln).rstrip() for ln in raw.splitlines()]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if not ln.strip():
                blank += 1
                if blank <= 1 and out:
                    out.append("")
                continue
            blank = 0
            out.append(ln.strip())
        return "\n".join(out).strip()


def _strip_html(value: str) -> str:
    """Readable markdown of a page's main content (structure preserved)."""
    # Many SPAs render a loading shell but embed the real article as hydration
    # JSON. Recover article-shaped objects generically before the HTML parser
    # intentionally drops script elements. This is based on fields, not on a
    # publisher, framework, URL, or JavaScript variable name.
    decoder = json.JSONDecoder()
    roots = []
    for match in re.finditer(r"(?:=|>)\s*(\{)", value or ""):
        try:
            candidate, _ = decoder.raw_decode(value, match.start(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            roots.append(candidate)
    articles: list[tuple[str, str]] = []
    stack = list(roots)
    while stack:
        candidate = stack.pop()
        if isinstance(candidate, dict):
            body = candidate.get("articleBody") or candidate.get("body")
            title = candidate.get("headline") or candidate.get("title") or ""
            if isinstance(body, str) and len(body.strip()) >= 160:
                articles.append((str(title), body))
            stack.extend(candidate.values())
        elif isinstance(candidate, list):
            stack.extend(candidate)
    if articles:
        title, body = max(articles, key=lambda item: len(item[1]))
        value = (f"<h1>{title}</h1>" if title else "") + body

    parser = _TextExtractor()
    try:
        parser.feed(value or "")
        parser.close()
        cleaned = parser.markdown()
        if cleaned:
            return cleaned
    except Exception:
        pass
    # Conservative fallback: blanket-strip every tag and unescape entities.
    cleaned = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", cleaned).strip()
