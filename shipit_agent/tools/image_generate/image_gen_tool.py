"""``image_generate`` — the agent makes an image, and sees it.

Turns a prompt into a real image via the active backend (see
:mod:`.providers`), saves the full-resolution PNG to a run cache, and returns it
as ``metadata["image_base64"]`` — the same channel ``computer_use`` screenshots
use — so a vision-capable model sees the result on its next turn and a UI can
render it inline.

The tool declares a ``check_fn``: when no backend has a key configured it is
**stripped from the toolset** (see :mod:`shipit_agent.tools.availability`), so
the model is never offered image generation it can't perform.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import IMAGE_GENERATE_PROMPT
from .providers import available_providers, build_image_provider

#: Cap the base64 fed back to the model — a 4 MB image is ~5.5 MB base64, which
#: is fine once but murders context if the agent makes several in a run.
_MAX_INLINE_BYTES = 6_000_000


def _image_backends_available() -> bool:
    return bool(available_providers())


class ImageGenerateTool:
    """Generate an image from a text prompt and return it inline."""

    name = "image_generate"
    description = (
        "Generate an image from a text description. Returns the image so you "
        "can see it and the user can view it. Use for illustrations, diagrams, "
        "mockups, icons — not for editing an existing file."
    )
    prompt_instructions = IMAGE_GENERATE_PROMPT

    #: Availability gate — hidden from the toolset when no backend is configured.
    check_fn = staticmethod(_image_backends_available)

    _SIZES = ("1024x1024", "1024x1536", "1536x1024")

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = (
            Path(output_dir).expanduser()
            if output_dir
            else Path.home() / ".shipit_agent" / "images"
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "What to draw — be specific about "
                            "subject, style, colours, composition.",
                        },
                        "size": {
                            "type": "string",
                            "enum": list(self._SIZES),
                            "description": "Square, portrait, or landscape.",
                            "default": "1024x1024",
                        },
                        "provider": {
                            "type": "string",
                            "description": "Backend name (optional; auto-selected).",
                        },
                    },
                    "required": ["prompt"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        prompt = str(kwargs.get("prompt", "")).strip()
        if not prompt:
            return ToolOutput(text="Error: 'prompt' is required.", metadata={"ok": False})
        size = str(kwargs.get("size") or "1024x1024")
        if size not in self._SIZES:
            size = "1024x1024"

        try:
            provider = build_image_provider(kwargs.get("provider"))
        except RuntimeError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})

        try:
            data = provider.generate(prompt, size=size)
        except Exception as err:  # noqa: BLE001 — surface any backend failure cleanly
            return ToolOutput(
                text=f"Error: {provider.name} could not generate the image: {err}",
                metadata={"ok": False, "provider": provider.name},
            )

        path = self._save(data)
        metadata: dict[str, Any] = {
            "ok": True,
            "provider": provider.name,
            "path": str(path),
            "size": size,
            "bytes": len(data),
        }
        # Feed the image back to the model via the shared vision bridge — unless
        # it's too big to be worth the context, in which case the path stands.
        if len(data) <= _MAX_INLINE_BYTES:
            metadata["image_base64"] = base64.b64encode(data).decode("ascii")
            metadata["media_type"] = "image/png"
            metadata["vision"] = True
        else:
            metadata["vision"] = False
            metadata["vision_skip_reason"] = (
                f"image is {len(data)} bytes — too large to inline; read it from {path}"
            )
        return ToolOutput(text=f"Image generated and saved: {path}", metadata=metadata)

    def _save(self, data: bytes) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"image-{int(time.time() * 1000)}.png"
        path.write_bytes(data)
        return path
