"""Convert a ``ParsedPrompt`` into a provider-agnostic multimodal message.

The output shape is the **Anthropic content-block format** (image source +
text blocks, interleaved). Both Anthropic native and the OpenAI-compat
adapter understand this shape — and LiteLLM normalizes both — so we only
need one canonical builder.

Example::

    >>> parsed = MediaParser().parse("Look at [https://x.com/a.png] please.")
    >>> build_multimodal_message(parsed, role="user")
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Look at "},
        {"type": "image", "source": {"type": "url", "url": "https://x.com/a.png"}},
        {"type": "text", "text": " please."},
      ]
    }
"""

from __future__ import annotations

from typing import Any

from .models import (
    MediaKind,
    MediaSegment,
    ParsedPrompt,
    TextSegment,
)


def build_multimodal_message(
    parsed: ParsedPrompt,
    *,
    role: str = "user",
    fallback: str = "markdown",
) -> dict[str, Any]:
    """Emit an Anthropic-shape message dict from a parsed prompt.

    Args:
        parsed: result of ``MediaParser.parse(...)``.
        role: ``"user"`` (default) or ``"assistant"`` — the role the LLM
            sees the message as.
        fallback: how to render media that can't be turned into a content
            block (currently only ``UNKNOWN`` kind):
              * ``"markdown"`` (default) — drop the URL into the text run as
                ``![alt](url)`` so the model still sees it.
              * ``"drop"`` — silently skip the reference.
              * ``"text"`` — replace with ``<media: alt>`` placeholder.

    Returns:
        ``{"role": role, "content": [...]}`` with content blocks in
        source order. If ``parsed`` has no media, ``content`` is just a
        single text block (or empty if the prompt was empty).
    """
    if fallback not in {"markdown", "drop", "text"}:
        raise ValueError(f"unknown fallback: {fallback!r}")

    blocks: list[dict[str, Any]] = []
    pending_text: list[str] = []

    def flush_text() -> None:
        if pending_text:
            text = "".join(pending_text)
            if text:
                blocks.append({"type": "text", "text": text})
            pending_text.clear()

    for seg in parsed.segments:
        if isinstance(seg, TextSegment):
            pending_text.append(seg.text)
            continue
        if isinstance(seg, MediaSegment):
            block = _media_block(seg.ref.kind, seg.ref.url, seg.ref.mime)
            if block is not None:
                flush_text()
                blocks.append(block)
                continue
            # Fallback path
            if fallback == "markdown":
                pending_text.append(seg.ref.to_markdown_placeholder())
            elif fallback == "text":
                label = seg.ref.alt or seg.ref.kind.value
                pending_text.append(f"<media: {label}>")
            # "drop" → omit entirely
            continue
    flush_text()

    if not blocks:
        # Empty prompt — keep at least an empty-string block so callers can
        # treat .content as a list uniformly.
        blocks = [{"type": "text", "text": ""}]

    return {"role": role, "content": blocks}


_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def image_block_from(source: str) -> dict[str, Any]:
    """An Anthropic-shape image block from whatever a caller has in hand.

    Accepts, in order of detection: an ``http(s)`` URL (URL-source block —
    adapters translate per provider), a local file path (read and base64d,
    so it works on every provider), or a raw base64 string (assumed PNG
    unless it carries a ``data:`` prefix naming the type).
    """
    import base64
    from pathlib import Path

    text = str(source).strip()
    if text.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": text}}
    if text.startswith("data:"):
        header, _, data = text.partition(",")
        media_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    path = Path(text)
    if path.exists() and path.is_file():
        media_type = _IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    # Last resort: treat as raw base64 payload.
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": text},
    }


#: Inline attachment budget for text/code files. Beyond this the model
#: should read the file with tools, not carry it in the prompt.
MAX_INLINE_FILE_CHARS = 100_000


def file_blocks_from(source: str) -> list[dict[str, Any]]:
    """Content blocks for an attached file of any kind.

    - Images → an image block (``image_block_from``).
    - PDFs → an Anthropic ``document`` block (native PDF reading where the
      provider supports it; adapters degrade it to a named placeholder
      elsewhere).
    - Everything else (text, markdown, code, config…) → a fenced text
    block with the filename as header — portable to every provider.
    """
    import base64
    from pathlib import Path

    path = Path(str(source).strip())
    if not path.exists() or not path.is_file():
        return [{"type": "text", "text": f"[attached file not found: {source}]"}]
    suffix = path.suffix.lower()
    if suffix in _IMAGE_MIME_BY_SUFFIX:
        return [image_block_from(str(path))]
    if suffix == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": data,
                },
                "title": path.name,
            }
        ]
    text = path.read_text(encoding="utf-8", errors="replace")
    clipped = ""
    if len(text) > MAX_INLINE_FILE_CHARS:
        text = text[:MAX_INLINE_FILE_CHARS]
        clipped = (
            f"\n…[truncated at {MAX_INLINE_FILE_CHARS:,} characters — "
            "read the file with tools for the rest]"
        )
    language = suffix.lstrip(".") or "text"
    return [
        {
            "type": "text",
            "text": (
                f"Attached file: {path.name}\n"
                f"```{language}\n{text}{clipped}\n```"
            ),
        }
    ]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _media_block(
    kind: MediaKind,
    url: str,
    mime: str | None,
) -> dict[str, Any] | None:
    """Map a ``(kind, url)`` to an Anthropic-shape content block.

    Returns ``None`` when the kind can't be turned into a real block (e.g.
    ``UNKNOWN``); the caller decides how to fall back.
    """
    if kind == MediaKind.IMAGE:
        return {
            "type": "image",
            "source": {"type": "url", "url": url, **({"media_type": mime} if mime else {})},
        }
    if kind == MediaKind.AUDIO:
        # Anthropic uses a similar shape for audio; LiteLLM normalises to
        # an OpenAI-style ``input_audio`` block when the provider needs it.
        return {
            "type": "audio",
            "source": {"type": "url", "url": url, **({"media_type": mime} if mime else {})},
        }
    if kind == MediaKind.VIDEO:
        return {
            "type": "video",
            "source": {"type": "url", "url": url, **({"media_type": mime} if mime else {})},
        }
    if kind == MediaKind.DOCUMENT:
        return {
            "type": "document",
            "source": {"type": "url", "url": url, **({"media_type": mime} if mime else {})},
        }
    return None
