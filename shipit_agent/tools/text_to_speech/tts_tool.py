"""``text_to_speech`` — the agent speaks.

Turns text into an audio file via the active backend (see :mod:`.providers`),
saves it, and returns the **path plus a ``MEDIA:<path>`` tag** — the convention a
chat/send pipeline turns into a playable voice message. Unlike an image, audio
isn't something a model "sees", so the return is a file reference, not inline
bytes.

The tool declares a ``check_fn``: with no backend available (no ``edge-tts``
installed and no key) it is stripped from the toolset and never offered.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import TEXT_TO_SPEECH_PROMPT
from .providers import available_providers, build_tts_provider

#: Guard against a runaway "read this whole document aloud" call.
_MAX_CHARS = 8_000


def _tts_backends_available() -> bool:
    return bool(available_providers())


class TextToSpeechTool:
    """Speak text — save an audio file and return its path."""

    name = "text_to_speech"
    description = (
        "Convert text to spoken audio. Saves an audio file and returns its path "
        "so a chat surface can play it. Use for a spoken summary or voice reply."
    )
    prompt_instructions = TEXT_TO_SPEECH_PROMPT

    #: Availability gate — hidden when no backend can run.
    check_fn = staticmethod(_tts_backends_available)

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = (
            Path(output_dir).expanduser()
            if output_dir
            else Path.home() / ".shipit_agent" / "audio"
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
                        "text": {"type": "string", "description": "The text to speak."},
                        "voice": {
                            "type": "string",
                            "description": "Voice name (optional; backend default otherwise).",
                        },
                        "provider": {
                            "type": "string",
                            "description": "Backend name (optional; auto-selected).",
                        },
                    },
                    "required": ["text"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        text = str(kwargs.get("text", "")).strip()
        if not text:
            return ToolOutput(text="Error: 'text' is required.", metadata={"ok": False})
        if len(text) > _MAX_CHARS:
            return ToolOutput(
                text=f"Error: text is {len(text)} chars — cap is {_MAX_CHARS}. "
                "Summarise or split it.",
                metadata={"ok": False},
            )

        try:
            provider = build_tts_provider(kwargs.get("provider"))
        except RuntimeError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})

        try:
            audio, ext = provider.synthesize(text, voice=kwargs.get("voice"))
        except Exception as err:  # noqa: BLE001 — surface any backend failure cleanly
            return ToolOutput(
                text=f"Error: {provider.name} could not synthesize speech: {err}",
                metadata={"ok": False, "provider": provider.name},
            )

        path = self._save(audio, ext)
        return ToolOutput(
            # The MEDIA: tag is what a send pipeline turns into a voice message.
            text=f"Audio generated and saved: {path}\nMEDIA:{path}",
            metadata={
                "ok": True,
                "provider": provider.name,
                "path": str(path),
                "format": ext,
                "bytes": len(audio),
                "media": str(path),
            },
        )

    def _save(self, audio: bytes, ext: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"speech-{int(time.time() * 1000)}.{ext}"
        path.write_bytes(audio)
        return path
