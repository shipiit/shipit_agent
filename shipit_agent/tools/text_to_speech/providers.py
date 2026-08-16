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
_PREFERENCE = ("edge", "openai", "gemini", "elevenlabs")


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

        key = opts.get("api_key") or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=key) if key else OpenAI()
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

        key = opts.get("api_key") or os.getenv("ELEVENLABS_API_KEY")
        client = ElevenLabs(api_key=key)
        audio = client.text_to_speech.convert(
            voice_id=voice or self.default_voice,
            model_id=str(opts.get("model") or "eleven_multilingual_v2"),
            text=text,
        )
        return b"".join(audio), "mp3"


class GeminiTTSProvider:
    """Google Gemini speech — ``gemini-2.5-flash-preview-tts``.

    Uses the ``google-genai`` SDK. The API returns raw PCM (24 kHz, 16-bit,
    mono), so we wrap it in a minimal WAV header — a self-contained, playable
    file with no extra dependency. Gated on a Gemini/Google API key.
    """

    name = "gemini"
    default_voice = "Kore"

    def is_available(self) -> bool:
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            return False
        import importlib.util

        return importlib.util.find_spec("google.genai") is not None

    def synthesize(self, text: str, *, voice: str | None = None, **opts: Any) -> tuple[bytes, str]:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=(opts.get("api_key") or os.getenv("GEMINI_API_KEY")
                     or os.getenv("GOOGLE_API_KEY"))
        )
        response = client.models.generate_content(
            model=str(opts.get("model") or "gemini-2.5-flash-preview-tts"),
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice or self.default_voice
                        )
                    )
                ),
            ),
        )
        pcm = response.candidates[0].content.parts[0].inline_data.data
        return _pcm_to_wav(pcm), "wav"


def _pcm_to_wav(pcm: bytes, *, rate: int = 24_000, channels: int = 1, width: int = 2) -> bytes:
    """Wrap raw PCM in a WAV container (stdlib only) — a playable file."""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


register_tts_provider(EdgeTTSProvider())
register_tts_provider(OpenAITTSProvider())
register_tts_provider(ElevenLabsTTSProvider())
register_tts_provider(GeminiTTSProvider())
