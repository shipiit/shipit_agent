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
