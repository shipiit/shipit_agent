"""``vision`` tool — analyse an image with a vision-capable LLM.

Pairs with :class:`~shipit_agent.tools.computer_use.ComputerUseTool` for a
capture -> analyse loop. Accepts a filesystem path, an ``http(s)`` URL, a
``data:image/...;base64,...`` data URL, or raw base64 and forwards it to a
vision-capable LLM adapter (Claude, GPT-4o, Gemini, Bedrock Claude, LiteLLM
in OpenAI-compatible format).

Design note on :class:`shipit_agent.models.Message`:
``Message.content`` is strictly typed as ``str`` today, so we cannot pass an
OpenAI-style list of parts through the type. Instead we:

* set ``content`` to a human-readable string that contains both the text
  prompt and a reference to the image (this is what non-vision adapters
  will see, and also what tests inspect), and
* stash the structured OpenAI-compatible parts list on
  ``metadata["parts"]`` and the raw image URL on ``metadata["image_url"]``
  so vision-aware adapters can opt in without changing the type.
"""

from __future__ import annotations

import base64 as _b64
import mimetypes
import re
from pathlib import Path
from typing import Any

from shipit_agent.models import Message
from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import VISION_PROMPT


_DETAIL_VALUES = ("low", "high", "auto")
_EXT_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Loose base64 sanity check — ignore whitespace, require >=16 chars of the
# base64 alphabet so we don't mistake short tokens like "hi" for images.
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{16,}$")


class VisionTool:
    """Send an image + question to a vision-capable LLM, return the analysis."""

    name = "vision"
    description = (
        "Send an image (file path, URL, data URL, or base64) to a "
        "vision-capable LLM and return a textual analysis."
    )
    prompt_instructions = (
        "Use vision to read screenshots, diagrams, UI mocks, error dialogs, "
        "whiteboard photos, and charts. Pair with computer_use for the "
        "capture -> analyse loop."
    )

    def __init__(self, *, llm: Any | None = None) -> None:
        self.llm = llm
        self.prompt = VISION_PROMPT

    # ── tool protocol ────────────────────────────────────────────

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image": {
                            "type": "string",
                            "description": (
                                "Image to analyse. One of: filesystem path, "
                                "http(s) URL, data URL "
                                "(`data:image/png;base64,...`), or raw base64."
                            ),
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "The question to ask about the image."
                            ),
                            "default": "Describe this image in detail.",
                        },
                        "detail": {
                            "type": "string",
                            "enum": list(_DETAIL_VALUES),
                            "description": (
                                "Vision detail hint — 'high' for OCR / "
                                "dense UI, 'low' for quick layout, 'auto' "
                                "lets the provider decide."
                            ),
                            "default": "auto",
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Upper bound on response tokens.",
                            "default": 1024,
                        },
                    },
                    "required": ["image"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        llm = self.llm or context.state.get("llm")
        if llm is None:
            return ToolOutput(
                text=(
                    "Vision tool requires an LLM adapter — pass one to "
                    "VisionTool(llm=...) or set context.state['llm']."
                ),
                metadata={"error": "no_llm"},
            )

        image_input = kwargs.get("image")
        if not image_input or not isinstance(image_input, str):
            return ToolOutput(
                text="Error: 'image' is required and must be a string.",
                metadata={"error": "bad_input"},
            )

        prompt_text = str(
            kwargs.get("prompt") or "Describe this image in detail."
        )
        detail = str(kwargs.get("detail") or "auto").lower()
        if detail not in _DETAIL_VALUES:
            detail = "auto"
        try:
            max_tokens = int(kwargs.get("max_tokens") or 1024)
        except (TypeError, ValueError):
            max_tokens = 1024

        resolved = _resolve_image(image_input)
        if resolved is None:
            return ToolOutput(
                text=(
                    f"Error: could not resolve image {image_input!r} — "
                    "not a URL, not an existing file, and not valid base64."
                ),
                metadata={"error": "image_not_found", "image": image_input},
            )

        parts: list[dict[str, Any]] = [
            {"type": "text", "text": prompt_text},
            {
                "type": "image_url",
                "image_url": {"url": resolved, "detail": detail},
            },
        ]

        # Keep content a string (Message.content is typed str), but make it
        # obvious both the prompt and the image reference are present — the
        # shortened data-URL form keeps things readable in logs/tests.
        content_str = (
            f"{prompt_text}\n\n[image_url: {_shorten(resolved)}]"
        )

        message = Message(
            role="user",
            content=content_str,
            metadata={
                "parts": parts,
                "image_url": resolved,
                "detail": detail,
            },
        )

        try:
            response = llm.complete(
                messages=[message],
                metadata={"max_tokens": max_tokens, "vision": True},
            )
        except TypeError:
            # Some minimal stubs won't accept `metadata=`; retry cleanly.
            response = llm.complete(messages=[message])

        response_text = getattr(response, "content", "") or ""
        usage = getattr(response, "usage", None) or {}
        model = getattr(llm, "model", None)

        return ToolOutput(
            text=response_text,
            metadata={
                "provider": "vision",
                "model": model,
                "usage": usage,
                "detail": detail,
                "image_url": resolved,
            },
        )


# ─────────────────────────── image resolution ───────────────────────────


def _resolve_image(image: str) -> str | None:
    """Normalise any supported image input into a URL or data URL.

    Returns ``None`` if the input doesn't match any supported form (e.g. a
    path-like string that doesn't exist on disk).
    """

    stripped = image.strip()
    if not stripped:
        return None

    # 1. Remote URL — pass through.
    low = stripped.lower()
    if low.startswith(("http://", "https://")):
        return stripped

    # 2. Existing data URL — pass through.
    if low.startswith("data:image/") and ";base64," in stripped:
        return stripped

    # 3. Local filesystem path.
    if _looks_like_path(stripped):
        path = Path(stripped).expanduser()
        if path.is_file():
            mime = _guess_mime(path)
            raw = path.read_bytes()
            b64 = _b64.b64encode(raw).decode("ascii")
            return f"data:{mime};base64,{b64}"
        # path-shaped string that doesn't exist — tell the caller.
        return None

    # 4. Raw base64 — wrap as PNG data URL.
    if _BASE64_RE.match(stripped):
        # Strip whitespace base64 sometimes picks up from line wraps.
        clean = re.sub(r"\s+", "", stripped)
        return f"data:image/png;base64,{clean}"

    return None


def _looks_like_path(value: str) -> bool:
    """Cheap heuristic: has a directory separator or a known image suffix."""

    if "/" in value or value.startswith(".") or value.startswith("~"):
        return True
    suffix = Path(value).suffix.lower()
    return suffix in _EXT_TO_MIME


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _EXT_TO_MIME:
        return _EXT_TO_MIME[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"


def _shorten(url: str, head: int = 48, tail: int = 8) -> str:
    if len(url) <= head + tail + 3:
        return url
    return f"{url[:head]}...{url[-tail:]}"
