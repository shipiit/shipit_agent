"""Dataclasses + enums for multimodal chat.

Core concept: a user's prompt is a list of ordered ``Segment``s — text
chunks interleaved with media references — preserving the exact spatial
order the user wrote. That's what makes "look at [a.png] then [b.png],
which is better?" feel natural to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class MediaKind(str, Enum):
    """Top-level kind of media a reference points to."""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class MediaReference:
    """One media item extracted from a user prompt.

    Created by ``MediaParser`` for each ``[url]``, ``![alt](url)``, or
    ``[media:<uuid>]`` syntax it finds. Carries enough info to:
    - know where in the source text it was (``start``, ``end``)
    - know what kind of media it is (``kind``)
    - render it back as a Markdown placeholder (``alt``)
    - validate against domain allowlists / size caps
    """

    url: str
    """Resolved fetchable URL. For ``[media:<uuid>]`` syntax, this is filled in
    by the ``MediaStore`` at parse time."""

    kind: MediaKind = MediaKind.UNKNOWN
    """Best-guess kind from MIME / file extension. ``UNKNOWN`` until
    validated; concrete LLM blocks need a known kind."""

    alt: str = ""
    """Alt text (from ``![alt](url)``) or empty for the bare-bracket form."""

    mime: str | None = None
    """Resolved MIME type (e.g. ``image/png``). Set during validation."""

    media_id: str | None = None
    """Set when the reference came from ``[media:<uuid>]`` syntax."""

    start: int = 0
    """Character index in the source string where the reference began."""

    end: int = 0
    """Character index where the reference ended (exclusive)."""

    raw: str = ""
    """The original raw token that was matched (e.g. ``[https://x.com/a.png]``)."""

    def to_markdown_placeholder(self) -> str:
        """Render as ``![alt](url)`` for fallback in text-only contexts."""
        return f"![{self.alt or self.kind.value}]({self.url})"


@dataclass(slots=True)
class TextSegment:
    """A run of plain text in a parsed prompt."""

    text: str

    @property
    def is_text(self) -> bool:
        return True

    @property
    def is_media(self) -> bool:
        return False


@dataclass(slots=True)
class MediaSegment:
    """A media reference embedded at a specific position in the prompt."""

    ref: MediaReference

    @property
    def is_text(self) -> bool:
        return False

    @property
    def is_media(self) -> bool:
        return True


# Union — segments are heterogeneous, but shipit avoids `|` in dataclass
# fields so we keep the explicit type alias here for clarity.
Segment = Union[TextSegment, MediaSegment]


@dataclass(slots=True)
class ParsedPrompt:
    """Result of parsing a user prompt for media references.

    Ordered list of segments. Every text run between media markers becomes
    a ``TextSegment``; every media reference becomes a ``MediaSegment``.
    The order matches exactly what the user wrote.
    """

    segments: list[Segment] = field(default_factory=list)
    """The interleaved segments in source order."""

    @property
    def media_refs(self) -> list[MediaReference]:
        """Convenience: all media references in order."""
        return [s.ref for s in self.segments if isinstance(s, MediaSegment)]

    @property
    def text(self) -> str:
        """Reconstruct the plain-text version, replacing media with markdown."""
        out: list[str] = []
        for seg in self.segments:
            if isinstance(seg, TextSegment):
                out.append(seg.text)
            else:
                out.append(seg.ref.to_markdown_placeholder())
        return "".join(out)

    @property
    def text_only(self) -> str:
        """Reconstruct text dropping media entirely.

        Useful for text-only LLMs that can't see images at all — the model
        still gets the surrounding context, just without the media.
        """
        return "".join(
            s.text for s in self.segments if isinstance(s, TextSegment)
        )

    @property
    def has_media(self) -> bool:
        return any(isinstance(s, MediaSegment) for s in self.segments)

    def __len__(self) -> int:
        return len(self.segments)
