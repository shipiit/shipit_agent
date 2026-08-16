"""Text-to-speech backends — one small registry, plug-in backends.

A TTS backend turns text into audio bytes. Each declares ``is_available()`` (a
cheap, no-network check) so the agent only offers speech when a backend can run.
Selection: an explicit name wins; else the single available backend; else a
preference walk filtered by availability.

Built-in: **Edge** (Microsoft Edge voices, *free, no key*), **OpenAI**
(``gpt-4o-mini-tts``), **ElevenLabs**. Others register with
:func:`register_tts_provider` — the same shape a plugin uses.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

#: Free-first preference, filtered by ``is_available()`` at resolve time.
_PREFERENCE = ("edge", "openai", "elevenlabs")


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def is_available(self) -> bool:
        """Cheap check — a key or dep present. No network."""

    def synthesize(self, text: str, *, voice: str | None = None, **opts: Any) -> tuple[bytes, str]:
        """Return ``(audio_bytes, extension)`` for ``text``. Raises on failure."""


_REGISTRY: dict[str, TTSProvider] = {}


def register_tts_provider(provider: TTSProvider) -> TTSProvider:
    _REGISTRY[provider.name] = provider
    return provider


def available_providers() -> list[str]:
    return [name for name, p in _REGISTRY.items() if _safe_available(p)]


def build_tts_provider(name: str | None = None) -> TTSProvider:
    if name:
        provider = _REGISTRY.get(name)
        if provider is None:
            known = ", ".join(sorted(_REGISTRY)) or "none registered"
            raise RuntimeError(f"Unknown TTS backend {name!r}. Known: {known}.")
        return provider
    usable = available_providers()
    if len(usable) == 1:
        return _REGISTRY[usable[0]]
    for candidate in _PREFERENCE:
        if candidate in usable:
            return _REGISTRY[candidate]
    if usable:
        return _REGISTRY[usable[0]]
    raise RuntimeError(
        "No text-to-speech backend is available. Install 'edge-tts' for free "
        "offline-key speech, or set OPENAI_API_KEY / ELEVENLABS_API_KEY."
    )


def _safe_available(provider: TTSProvider) -> bool:
    try:
        return bool(provider.is_available())
    except Exception:  # noqa: BLE001 — a broken probe means "unavailable"
        return False


# ── built-in backends ──────────────────────────────────────────────────────


class EdgeTTSProvider:
    """Microsoft Edge neural voices via the ``edge-tts`` package — free, no key."""

    name = "edge"
    default_voice = "en-US-AriaNeural"

    def is_available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("edge_tts") is not None

    def synthesize(self, text: str, *, voice: str | None = None, **opts: Any) -> tuple[bytes, str]:
        import asyncio

        import edge_tts

        communicate = edge_tts.Communicate(text, voice or self.default_voice)

        async def _collect() -> bytes:
            buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer += chunk["data"]
            return bytes(buffer)

        return asyncio.run(_collect()), "mp3"


class OpenAITTSProvider:
    """OpenAI speech — ``gpt-4o-mini-tts`` (default) or ``tts-1``."""

    name = "openai"
    default_voice = "alloy"

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def synthesize(self, text: str, *, voice: str | None = None, **opts: Any) -> tuple[bytes, str]:
        from openai import OpenAI

        client = OpenAI()
        result = client.audio.speech.create(
            model=str(opts.get("model") or "gpt-4o-mini-tts"),
            voice=voice or self.default_voice,
            input=text,
        )
        return result.read(), "mp3"


class ElevenLabsTTSProvider:
    """ElevenLabs — ``eleven_multilingual_v2``."""

    name = "elevenlabs"
    default_voice = "Rachel"

    def is_available(self) -> bool:
        return bool(os.getenv("ELEVENLABS_API_KEY"))

    def synthesize(self, text: str, *, voice: str | None = None, **opts: Any) -> tuple[bytes, str]:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        audio = client.text_to_speech.convert(
            voice_id=voice or self.default_voice,
            model_id=str(opts.get("model") or "eleven_multilingual_v2"),
            text=text,
        )
        return b"".join(audio), "mp3"


register_tts_provider(EdgeTTSProvider())
register_tts_provider(OpenAITTSProvider())
register_tts_provider(ElevenLabsTTSProvider())
