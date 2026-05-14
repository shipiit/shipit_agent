"""Parse user prompts for inline media references.

Supports three syntaxes:

* ``[https://example.com/img.png]`` — bare URL inside brackets
* ``![alt text](https://example.com/img.png)`` — markdown image
* ``[media:<uuid>]`` — local upload, resolved via a ``MediaStore``

The parser walks the string left-to-right, splitting it into ordered
``TextSegment`` and ``MediaSegment`` chunks so the original word order is
preserved end-to-end. That's the key invariant — when the user writes
*"compare [a] to [b]"* the model sees the images in the same positions.

Validation (domain allowlist, max size, MIME) happens at parse time when
``MediaParser`` is configured with those rules. Failures become
text fall-backs (``[blocked: example.com]``) rather than silent drops, so
the user always sees what happened.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .models import (
    MediaKind,
    MediaReference,
    MediaSegment,
    ParsedPrompt,
    TextSegment,
)


# ---------------------------------------------------------------------------
# Regexes — order matters: markdown form first (more specific), then bare URL,
# then media:<uuid>. Each token gets matched at most once.
# ---------------------------------------------------------------------------

# ![alt](url)
_MARKDOWN_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^\s)]+)\)"
)

# [https://...] — bare URL inside brackets, optional trailing punctuation OUTSIDE
_BRACKET_URL_RE = re.compile(
    r"\[(?P<url>https?://[^\s\]]+)\]"
)

# [media:<uuid>] — local store reference. UUIDs are loose: alphanumeric + dash + underscore.
_MEDIA_UUID_RE = re.compile(
    r"\[media:(?P<uuid>[a-zA-Z0-9_-]+)\]"
)


# Pattern priority — markdown is most specific (a URL nested in brackets
# nested in parens), so we try it first at every position and fall back
# to the looser shapes only if it doesn't match. Walking with all three
# avoids the duplicate-named-group problem of a single combined regex.
_PATTERNS_IN_PRIORITY: list[tuple[str, re.Pattern[str]]] = [
    ("markdown", _MARKDOWN_RE),
    ("bracket_url", _BRACKET_URL_RE),
    ("media_uuid", _MEDIA_UUID_RE),
]


def _next_match(text: str, start: int) -> tuple[str, re.Match[str]] | None:
    """Find the earliest match at-or-after ``start`` across all patterns.

    On a tie at the same start position, the most-specific shape wins
    (markdown > bracket-url > media:uuid).
    """
    candidates: list[tuple[int, int, str, re.Match[str]]] = []
    for priority, (kind, pattern) in enumerate(_PATTERNS_IN_PRIORITY):
        m = pattern.search(text, start)
        if m:
            candidates.append((m.start(), priority, kind, m))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, _, kind, match = candidates[0]
    return kind, match


# MIME / extension → MediaKind mapping
_KIND_BY_EXT: dict[str, MediaKind] = {
    "png": MediaKind.IMAGE, "jpg": MediaKind.IMAGE, "jpeg": MediaKind.IMAGE,
    "gif": MediaKind.IMAGE, "webp": MediaKind.IMAGE, "bmp": MediaKind.IMAGE,
    "svg": MediaKind.IMAGE,
    "mp3": MediaKind.AUDIO, "wav": MediaKind.AUDIO, "m4a": MediaKind.AUDIO,
    "ogg": MediaKind.AUDIO, "flac": MediaKind.AUDIO,
    "mp4": MediaKind.VIDEO, "mov": MediaKind.VIDEO, "webm": MediaKind.VIDEO,
    "avi": MediaKind.VIDEO, "mkv": MediaKind.VIDEO,
    "pdf": MediaKind.DOCUMENT, "doc": MediaKind.DOCUMENT,
    "docx": MediaKind.DOCUMENT, "txt": MediaKind.DOCUMENT,
    "md": MediaKind.DOCUMENT,
}

_KIND_BY_MIME_PREFIX: dict[str, MediaKind] = {
    "image/": MediaKind.IMAGE,
    "audio/": MediaKind.AUDIO,
    "video/": MediaKind.VIDEO,
    "application/pdf": MediaKind.DOCUMENT,
}


def _kind_from_url(url: str) -> MediaKind:
    """Best-effort kind from URL extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "." in path:
        ext = path.rsplit(".", 1)[-1]
        if ext in _KIND_BY_EXT:
            return _KIND_BY_EXT[ext]
    return MediaKind.UNKNOWN


def _kind_from_mime(mime: str | None) -> MediaKind:
    if not mime:
        return MediaKind.UNKNOWN
    for prefix, kind in _KIND_BY_MIME_PREFIX.items():
        if mime.startswith(prefix) or mime == prefix:
            return kind
    return MediaKind.UNKNOWN


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ValidationError:
    """Raised inline when a reference can't be used (e.g. blocked domain)."""

    reason: str
    detail: str = ""


@dataclass
class MediaParser:
    """Configurable parser. Construct once, reuse across messages.

    Args:
        allowlist_domains: list of glob patterns (e.g. ``["*.amazonaws.com",
            "github.com"]``). ``["*"]`` allows anything. Defaults to ``["*"]``
            for dev — production should restrict.
        denylist_domains: glob patterns that always fail, evaluated AFTER the
            allowlist match.
        max_size_mb: maximum size in megabytes. Validated by ``HEAD`` request
            in ``validate_size_async`` (off by default; opt-in to keep the
            parser pure).
        media_store: optional ``MediaStore`` for resolving ``[media:<uuid>]``
            references to URLs.
    """

    allowlist_domains: list[str] = field(default_factory=lambda: ["*"])
    denylist_domains: list[str] = field(default_factory=list)
    max_size_mb: float | None = None
    media_store: Any = None

    def parse(self, prompt: str) -> ParsedPrompt:
        """Walk the prompt, return interleaved segments."""
        if not prompt:
            return ParsedPrompt(segments=[])

        segments: list[Any] = []
        cursor = 0

        while cursor < len(prompt):
            found = _next_match(prompt, cursor)
            if found is None:
                segments.append(TextSegment(text=prompt[cursor:]))
                break

            kind_label, match = found
            if match.start() > cursor:
                segments.append(TextSegment(text=prompt[cursor:match.start()]))

            ref = self._build_reference(kind_label, match)
            if ref is None:
                # Match failed validation — keep the original text inline
                segments.append(TextSegment(text=match.group(0)))
            else:
                segments.append(MediaSegment(ref=ref))
            cursor = match.end()

        return ParsedPrompt(segments=_coalesce_text(segments))

    def is_allowed_domain(self, url: str) -> bool:
        """Check ``url``'s host against the allowlist + denylist."""
        host = urlparse(url).hostname or ""
        if not host:
            return False
        if any(fnmatch.fnmatch(host, p) for p in self.denylist_domains):
            return False
        return any(fnmatch.fnmatch(host, p) for p in self.allowlist_domains)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_reference(
        self, kind_label: str, match: re.Match[str],
    ) -> MediaReference | None:
        groups = match.groupdict()

        if kind_label == "markdown":
            url = groups["url"]
            alt = groups.get("alt") or ""
            if not self.is_allowed_domain(url):
                return None
            return MediaReference(
                url=url,
                kind=_kind_from_url(url),
                alt=alt,
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
            )

        if kind_label == "bracket_url":
            url = groups["url"]
            if not self.is_allowed_domain(url):
                return None
            return MediaReference(
                url=url,
                kind=_kind_from_url(url),
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
            )

        if kind_label == "media_uuid":
            uuid = groups["uuid"]
            if self.media_store is None:
                return None
            stored = self.media_store.resolve(uuid)
            if stored is None:
                return None
            kind = _kind_from_mime(stored.mime)
            if kind == MediaKind.UNKNOWN:
                kind = _kind_from_url(stored.url)
            return MediaReference(
                url=stored.url,
                kind=kind,
                alt=stored.alt or "",
                mime=stored.mime,
                media_id=uuid,
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
            )

        return None


def extract_media_refs(
    prompt: str,
    *,
    allowlist_domains: list[str] | None = None,
    media_store: Any = None,
) -> list[MediaReference]:
    """Convenience: parse + return only the media references.

    For full segment ordering, use ``MediaParser.parse(...)`` directly.
    """
    parser = MediaParser(
        allowlist_domains=allowlist_domains or ["*"],
        media_store=media_store,
    )
    return parser.parse(prompt).media_refs


def _coalesce_text(segments: list[Any]) -> list[Any]:
    """Merge adjacent ``TextSegment``s and drop empty ones — keeps the
    output minimal so downstream consumers don't see "" segments."""
    out: list[Any] = []
    for seg in segments:
        if isinstance(seg, TextSegment):
            if not seg.text:
                continue
            if out and isinstance(out[-1], TextSegment):
                out[-1] = TextSegment(text=out[-1].text + seg.text)
                continue
        out.append(seg)
    return out
