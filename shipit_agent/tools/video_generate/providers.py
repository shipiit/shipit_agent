"""Video-generation backends — one small registry, plug-in backends.

A video backend turns a prompt into an MP4. Generation is slow and *asynchronous*
at the API — a job is submitted, then polled until the clip is ready — so unlike
image or speech a backend's :meth:`generate` **blocks internally** (submit → poll
→ download) and hands back finished bytes. The tool stays a plain synchronous call
like every other; the waiting is the backend's problem, not the model's.

Each backend declares ``is_available()`` (a cheap, no-network check — an API key
present) so the agent only offers video when a backend can actually run.
Selection: an explicit name wins; else the single available backend; else a
preference walk filtered by availability. New backends register with
:func:`register_video_provider` — the same shape a plugin would use.

Built-in: **Fal** (``FAL_KEY``) and **Replicate** (``REPLICATE_API_TOKEN``) —
both hosted, both key-gated. Others (Runway, Luma, an xAI model) drop in the same
way without touching the tool.
"""

from __future__ import annotations

import os
import urllib.request
from typing import Any, Protocol, runtime_checkable

#: Preference order, filtered by ``is_available()`` at resolve time.
_PREFERENCE = ("fal", "replicate")


@runtime_checkable
class VideoProvider(Protocol):
    name: str

    def is_available(self) -> bool:
        """Cheap check — a key present. No network."""

    def generate(
        self, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9", **opts: Any
    ) -> tuple[bytes, str]:
        """Return ``(video_bytes, extension)`` for ``prompt``. Blocks until ready."""


_REGISTRY: dict[str, VideoProvider] = {}


def register_video_provider(provider: VideoProvider) -> VideoProvider:
    """Add (or override) a video backend, keyed by ``provider.name``."""
    _REGISTRY[provider.name] = provider
    return provider


def available_providers() -> list[str]:
    """Names of backends that can run right now (key present)."""
    return [name for name, p in _REGISTRY.items() if _safe_available(p)]


def build_video_provider(name: str | None = None) -> VideoProvider:
    """Resolve the backend to use.

    Explicit ``name`` wins (even if unavailable, so the caller gets a precise
    error). Else the single available backend; else the first available in the
    preference order. Raises ``RuntimeError`` when nothing is configured.
    """
    if name:
        provider = _REGISTRY.get(name)
        if provider is None:
            known = ", ".join(sorted(_REGISTRY)) or "none registered"
            raise RuntimeError(f"Unknown video backend {name!r}. Known: {known}.")
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
        "No video-generation backend is configured. Set FAL_KEY or "
        "REPLICATE_API_TOKEN (or register another backend) to enable video_generate."
    )


def _safe_available(provider: VideoProvider) -> bool:
    try:
        return bool(provider.is_available())
    except Exception:  # noqa: BLE001 — a broken probe means "unavailable"
        return False


def _allow_unknown_model() -> bool:
    """Escape hatch — turn off validation entirely for an edge case."""
    return os.getenv("SHIPIT_ALLOW_UNKNOWN_VIDEO_MODEL", "").lower() in ("1", "true", "yes")


#: Substrings that mark a *text/chat* model — never valid on a video endpoint.
#: The validation is deliberately a small **denylist**, not an allow-list: video
#: catalogs are large and grow weekly, so we permit anything that isn't obviously
#: a language model and let the backend do the final say. This catches the one
#: real mistake — pointing SHIPIT_VIDEO_MODEL at a chat model — without blocking
#: legitimate new video models we've never heard of.
_CHAT_MODEL_HINTS = (
    "gpt-3", "gpt-4", "gpt-5", "o1-", "o3-", "chat", "instruct", "claude",
    "sonnet", "haiku", "opus", "gemini-1", "gemini-2", "gemini-flash", "gemini-pro",
    "llama", "mistral", "mixtral", "qwen", "deepseek-chat", "-chat", "embed",
    "text-embedding", "whisper", "tts", "dall-e", "gpt-image", "imagen",
)


def validate_video_model(backend: str, model: str, known: tuple[str, ...] = ()) -> None:
    """Reject a model that is clearly not a text-to-video model.

    Permissive by design — an unrecognised model is *allowed* (the backend
    validates it for real), because no static list can keep up with every
    provider's video catalog. What's rejected is a model whose name marks it as a
    chat/text/image/audio model, which would fail deep inside the provider with an
    opaque error. ``known`` models always pass; ``SHIPIT_ALLOW_UNKNOWN_VIDEO_MODEL``
    turns the check off entirely.
    """
    if _allow_unknown_model():
        return
    if not model:
        raise RuntimeError(
            f"No {backend} video model set. Try one of: {', '.join(known)}."
        )
    if model in known:
        return
    lowered = model.lower()
    for hint in _CHAT_MODEL_HINTS:
        if hint in lowered:
            raise RuntimeError(
                f"{model!r} looks like a text/chat/image model, not a text-to-video "
                f"model — it can't generate video. Use a video model (e.g. "
                f"{', '.join(known[:3]) or 'a provider video model'}), or set "
                "SHIPIT_ALLOW_UNKNOWN_VIDEO_MODEL=1 if you're sure."
            )


def _download(url: str, *, timeout: int = 300) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
        return resp.read()


# ── built-in backends ──────────────────────────────────────────────────────


class FalVideoProvider:
    """Fal-hosted text-to-video. ``fal_client.subscribe`` polls to completion."""

    name = "fal"
    #: A sensible default text-to-video model; override with ``model=`` or
    #: ``SHIPIT_VIDEO_MODEL``.
    default_model = "fal-ai/ltx-video"
    #: Common text-to-video models on fal — hints in error messages, not a gate.
    known_models = (
        "fal-ai/ltx-video",
        "fal-ai/kling-video/v1/standard/text-to-video",
        "fal-ai/minimax-video",
        "fal-ai/hunyuan-video",
        "fal-ai/mochi-v1",
    )

    def is_available(self) -> bool:
        return bool(os.getenv("FAL_KEY"))

    def generate(
        self, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9", **opts: Any
    ) -> tuple[bytes, str]:
        model = str(opts.get("model") or os.getenv("SHIPIT_VIDEO_MODEL") or self.default_model)
        validate_video_model(self.name, model, self.known_models)

        import fal_client  # imported lazily — optional dependency
        result = fal_client.subscribe(
            model,
            arguments={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
            },
        )
        # fal returns {"video": {"url": ...}} (or a "videos" list for some models).
        video = result.get("video") or (result.get("videos") or [{}])[0]
        url = video.get("url") if isinstance(video, dict) else None
        if not url:
            raise RuntimeError("fal video backend returned no video url")
        return _download(url), "mp4"


class ReplicateVideoProvider:
    """Replicate-hosted text-to-video. ``replicate.run`` blocks to completion."""

    name = "replicate"
    default_model = "minimax/video-01"
    #: Common text-to-video models on Replicate — hints in error messages, not a gate.
    known_models = (
        "minimax/video-01",
        "tencent/hunyuan-video",
        "genmoai/mochi-1",
        "lightricks/ltx-video",
        "kwaivgi/kling-v1.6-standard",
    )

    def is_available(self) -> bool:
        return bool(os.getenv("REPLICATE_API_TOKEN"))

    def generate(
        self, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9", **opts: Any
    ) -> tuple[bytes, str]:
        model = str(opts.get("model") or os.getenv("SHIPIT_VIDEO_MODEL") or self.default_model)
        validate_video_model(self.name, model, self.known_models)

        import replicate  # imported lazily — optional dependency
        output = replicate.run(model, input={"prompt": prompt})
        # Output is a URL string, a list of them, or a FileOutput with .read()/.url.
        if isinstance(output, (list, tuple)):
            output = output[0] if output else None
        if output is None:
            raise RuntimeError("replicate video backend returned no output")
        if hasattr(output, "read"):
            return output.read(), "mp4"
        url = getattr(output, "url", None) or str(output)
        return _download(url), "mp4"


# Register the built-in backends at import.
register_video_provider(FalVideoProvider())
register_video_provider(ReplicateVideoProvider())
