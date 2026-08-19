"""Adapting message content and history to what each endpoint accepts.

Three things differ per model family, none of them a request parameter, all of
them previously an ``if provider ==`` branch in the runtime:

**Image sources.** ``bedrock-mantle`` accepts base64 data URLs and ``s3://``
URLs; arbitrary public ``https://`` image URLs are not supported. Passing one
through produces an error that names the image, not the cause. Here the URL is
either inlined (when a fetcher is supplied) or replaced with an explicit note
the model can act on — never silently forwarded to fail.

**Block order.** Google recommends image content before text for Gemma 4. The
reordering is stable, so text blocks keep their relative order among themselves.

**Reasoning history.** Two families have opposite, equally strict contracts:
DeepSeek thinking mode *requires* ``reasoning_content`` to be replayed on prior
assistant messages that emitted tool calls, and Gemma 4 *requires* that prior
reasoning is not sent back at all, because replaying it degrades responses.
One policy field, read from capabilities, decides which. Reasoning is always
kept in the run's own event trace either way — stripping applies only to what
is sent onward.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Iterable, Protocol, Sequence

from shipit_agent.llms.capabilities import ModelCapabilities, capabilities_for

logger = logging.getLogger(__name__)

__all__ = [
    "ImageFetcher",
    "normalize_content",
    "normalize_messages",
    "apply_reasoning_policy",
    "strip_reasoning",
    "UnsupportedImageSource",
]


class UnsupportedImageSource(ValueError):
    """An image source this endpoint cannot accept and we cannot convert."""


class ImageFetcher(Protocol):
    """Fetches an image URL, returning ``(bytes, media_type)``."""

    def __call__(self, url: str) -> tuple[bytes, str]: ...


class _MessageLike(Protocol):
    role: str
    content: Any
    metadata: dict[str, Any]


# --------------------------------------------------------------------------- #
# Image sources
# --------------------------------------------------------------------------- #


def _source_kind(url: str) -> str:
    lowered = url.strip().lower()
    if lowered.startswith("data:"):
        return "base64"
    if lowered.startswith("s3://"):
        return "s3"
    if lowered.startswith(("http://", "https://")):
        return "url"
    return "unknown"


def _as_data_url(payload: bytes, media_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _rewrite_image_block(
    block: dict[str, Any],
    caps: ModelCapabilities,
    fetcher: ImageFetcher | None,
    *,
    strict: bool,
) -> dict[str, Any]:
    """Return *block* unchanged, converted, or replaced with an honest note."""
    image = block.get("image_url")
    url = image.get("url") if isinstance(image, dict) else block.get("url")
    if not isinstance(url, str) or not url:
        return block

    kind = _source_kind(url)
    if kind in caps.image_sources:
        return block

    if kind == "url" and fetcher is not None:
        try:
            payload, media_type = fetcher(url)
        except Exception as exc:  # noqa: BLE001 — a bad image is not fatal
            logger.debug("Could not fetch %s for inlining: %s", url, exc)
        else:
            if "base64" in caps.image_sources:
                return {
                    **block,
                    "image_url": {"url": _as_data_url(payload, media_type)},
                }

    message = (
        f"[image omitted: this endpoint accepts "
        f"{', '.join(sorted(caps.image_sources))} sources, not {kind!r}]"
    )
    if strict:
        raise UnsupportedImageSource(message)
    logger.debug("%s (%s)", message, url)
    return {"type": "text", "text": message}


def _ordered(blocks: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """Stable reordering — relative order within each class is preserved."""
    if order == "any":
        return blocks

    def is_image(block: dict[str, Any]) -> bool:
        return str(block.get("type", "")).startswith("image")

    if order == "image_first":
        return [b for b in blocks if is_image(b)] + [
            b for b in blocks if not is_image(b)
        ]
    return [b for b in blocks if not is_image(b)] + [b for b in blocks if is_image(b)]


def normalize_content(
    content: Any,
    *,
    model: str | None = None,
    caps: ModelCapabilities | None = None,
    fetcher: ImageFetcher | None = None,
    strict: bool = False,
) -> Any:
    """Adapt one message's content to *model*'s accepted wire format.

    Plain strings pass through untouched. Block lists have unsupported image
    sources converted or replaced, then are reordered per the family's
    recommendation. ``strict=True`` raises instead of substituting a note,
    for callers that would rather fail than send a degraded prompt.
    """
    if not isinstance(content, list):
        return content
    caps = caps or capabilities_for(model)

    rewritten: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            rewritten.append({"type": "text", "text": str(block)})
            continue
        if str(block.get("type", "")).startswith("image"):
            rewritten.append(_rewrite_image_block(block, caps, fetcher, strict=strict))
        else:
            rewritten.append(block)

    return _ordered(rewritten, caps.content_block_order)


# --------------------------------------------------------------------------- #
# Reasoning history
# --------------------------------------------------------------------------- #

#: Keys under which adapters have stored a turn's reasoning.
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


def strip_reasoning(message: _MessageLike) -> _MessageLike:
    """Remove reasoning from *message*'s metadata, leaving it otherwise intact.

    Returns the same object when there is nothing to strip, so the common case
    allocates nothing. The run's event trace is untouched — only what is sent
    back to the model is affected.
    """
    metadata = getattr(message, "metadata", None)
    if not isinstance(metadata, dict):
        return message
    if not any(key in metadata for key in _REASONING_KEYS):
        return message
    cleaned = {k: v for k, v in metadata.items() if k not in _REASONING_KEYS}
    replace_fn: Callable[..., Any] | None = getattr(message, "__class__", None)
    if replace_fn is None:
        return message
    clone = replace_fn(
        role=message.role,
        content=message.content,
        name=getattr(message, "name", None),
        metadata=cleaned,
    )
    return clone


def apply_reasoning_policy(
    messages: Sequence[_MessageLike],
    *,
    model: str | None = None,
    caps: ModelCapabilities | None = None,
) -> list[_MessageLike]:
    """Prepare history according to the family's reasoning contract.

    ``replay`` returns the messages untouched (DeepSeek requires the prior
    reasoning). ``strip`` removes it (Gemma 4 degrades if it is replayed).
    ``ignore`` also strips, since reasoning has no meaning in that history.
    """
    caps = caps or capabilities_for(model)
    if caps.reasoning_history == "replay":
        return list(messages)
    return [strip_reasoning(message) for message in messages]


def normalize_messages(
    messages: Iterable[_MessageLike],
    *,
    model: str | None = None,
    fetcher: ImageFetcher | None = None,
    strict: bool = False,
) -> list[_MessageLike]:
    """Apply content and reasoning adaptation to a whole history."""
    caps = capabilities_for(model)
    adapted: list[_MessageLike] = []
    for message in messages:
        content = normalize_content(
            message.content, caps=caps, fetcher=fetcher, strict=strict
        )
        if content is message.content:
            adapted.append(message)
            continue
        adapted.append(
            message.__class__(
                role=message.role,
                content=content,
                name=getattr(message, "name", None),
                metadata=dict(getattr(message, "metadata", {}) or {}),
            )
        )
    return apply_reasoning_policy(adapted, caps=caps)
