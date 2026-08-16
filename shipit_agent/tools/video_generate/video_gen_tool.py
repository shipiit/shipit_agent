"""``video_generate`` — the agent makes a short video.

Turns a prompt into an MP4 via the active backend (see :mod:`.providers`), saves
it, and returns the **path plus a ``MEDIA:<path>`` tag** — the convention a
chat/send pipeline turns into a playable clip. A video is megabytes, so unlike an
image it is *not* fed back inline; the model gets a file reference, not bytes.

The tool declares a ``check_fn``: with no backend key configured it is stripped
from the toolset and never offered.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import VIDEO_GENERATE_PROMPT
from .providers import available_providers, build_video_provider

#: Guard against a runaway prompt; clip length is what actually costs, capped below.
_MAX_CHARS = 2_000
#: Keep clips short — long generations are slow and expensive.
_MAX_DURATION = 30
_ASPECT_RATIOS = ("16:9", "9:16", "1:1")


def _video_backends_available() -> bool:
    return bool(available_providers())


class VideoGenerateTool:
    """Generate a short video from a text prompt; save it and return its path."""

    name = "video_generate"
    description = (
        "Generate a short video clip from a text description. Saves an MP4 and "
        "returns its path so a chat surface can play it. Use for b-roll, product "
        "shots, animations, concept scenes — not for editing existing footage."
    )
    prompt_instructions = VIDEO_GENERATE_PROMPT

    #: Availability gate — hidden when no backend is configured.
    check_fn = staticmethod(_video_backends_available)

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = (
            Path(output_dir).expanduser()
            if output_dir
            else Path.home() / ".shipit_agent" / "videos"
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
                            "description": "What to film — subject, motion, "
                            "camera, style.",
                        },
                        "duration": {
                            "type": "integer",
                            "description": f"Clip length in seconds (1–{_MAX_DURATION}).",
                            "default": 5,
                        },
                        "aspect_ratio": {
                            "type": "string",
                            "enum": list(_ASPECT_RATIOS),
                            "description": "Landscape, portrait, or square.",
                            "default": "16:9",
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
        if len(prompt) > _MAX_CHARS:
            return ToolOutput(
                text=f"Error: prompt is {len(prompt)} chars — cap is {_MAX_CHARS}.",
                metadata={"ok": False},
            )
        duration = self._clamp_duration(kwargs.get("duration"))
        aspect = str(kwargs.get("aspect_ratio") or "16:9")
        if aspect not in _ASPECT_RATIOS:
            aspect = "16:9"

        try:
            provider = build_video_provider(kwargs.get("provider"))
        except RuntimeError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})

        try:
            video, ext = provider.generate(prompt, duration=duration, aspect_ratio=aspect)
        except Exception as err:  # noqa: BLE001 — surface any backend failure cleanly
            return ToolOutput(
                text=f"Error: {provider.name} could not generate the video: {err}",
                metadata={"ok": False, "provider": provider.name},
            )

        path = self._save(video, ext)
        return ToolOutput(
            # The MEDIA: tag is what a send pipeline turns into a playable clip.
            text=f"Video generated and saved: {path}\nMEDIA:{path}",
            metadata={
                "ok": True,
                "provider": provider.name,
                "path": str(path),
                "format": ext,
                "bytes": len(video),
                "duration": duration,
                "aspect_ratio": aspect,
                "media": str(path),
            },
        )

    @staticmethod
    def _clamp_duration(value: Any) -> int:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return 5
        return max(1, min(seconds, _MAX_DURATION))

    def _save(self, video: bytes, ext: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"video-{int(time.time() * 1000)}.{ext}"
        path.write_bytes(video)
        return path
