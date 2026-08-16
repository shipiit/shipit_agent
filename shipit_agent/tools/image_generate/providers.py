"""Image-generation backends — one small registry, plug-in backends.

An image backend turns a prompt into PNG bytes. Each declares ``is_available()``
(a cheap, no-network check — an env key present) so the agent only offers image
generation when a backend can actually run. Selection is: an explicit name wins;
else the single available backend; else a preference walk filtered by
availability. New backends register with :func:`register_image_provider` — the
same shape a plugin would use.

Built-in: OpenAI (``gpt-image-1`` / ``dall-e-3``). Others (fal, openrouter,
stability) drop in as backends without touching the tool.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Protocol, runtime_checkable

#: Legacy-preference order, filtered by ``is_available()`` at resolve time.
_PREFERENCE = ("openai", "litellm", "fal", "openrouter")


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    def is_available(self) -> bool:
        """Cheap check — a key/dep present. No network."""

    def generate(self, prompt: str, *, size: str = "1024x1024", **opts: Any) -> bytes:
        """Return PNG bytes for ``prompt``. Raises on failure."""


_REGISTRY: dict[str, ImageProvider] = {}


def register_image_provider(provider: ImageProvider) -> ImageProvider:
    """Add (or override) an image backend, keyed by ``provider.name``."""
    _REGISTRY[provider.name] = provider
    return provider


def available_providers() -> list[str]:
    """Names of backends that can run right now (key present)."""
    return [name for name, p in _REGISTRY.items() if _safe_available(p)]


def build_image_provider(name: str | None = None) -> ImageProvider:
    """Resolve the backend to use.

    Explicit ``name`` wins (even if unavailable, so the caller gets a precise
    error). Else the single available backend; else the first available in the
    preference order. Raises ``RuntimeError`` when nothing is configured.
    """
    if name:
        provider = _REGISTRY.get(name)
        if provider is None:
            known = ", ".join(sorted(_REGISTRY)) or "none registered"
            raise RuntimeError(f"Unknown image backend {name!r}. Known: {known}.")
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
        "No image-generation backend is configured. Set OPENAI_API_KEY (or "
        "register another backend) to enable image_generate."
    )


def _safe_available(provider: ImageProvider) -> bool:
    try:
        return bool(provider.is_available())
    except Exception:  # noqa: BLE001 — a broken probe means "unavailable"
        return False


def _allow_unknown_model() -> bool:
    """Escape hatch — turn model validation off for an edge case."""
    return os.getenv("SHIPIT_ALLOW_UNKNOWN_IMAGE_MODEL", "").lower() in ("1", "true", "yes")


#: Names that positively mark an *image-generation* model. If any appears the
#: model is accepted outright — this is what keeps a legitimate image model whose
#: name also looks chatty (``gemini-2.5-flash-image``) from being rejected.
_IMAGE_MODEL_HINTS = (
    "image", "imagen", "imagegeneration", "dall-e", "dalle", "flux", "sdxl",
    "stable-diffusion", "diffusion", "stability", "recraft", "ideogram", "photon",
)

#: Names that mark a chat / text / audio / video model — never an image model
#: (checked only when no positive image hint is present).
_NON_IMAGE_HINTS = (
    "gpt-3", "gpt-4", "gpt-5", "o1-", "o3-", "chat", "instruct", "claude",
    "sonnet", "haiku", "opus", "llama", "mistral", "mixtral", "qwen", "deepseek",
    "gemini-1.5", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-pro", "embed",
    "whisper", "tts", "video", "sora", "veo",
)


def validate_image_model(backend: str, model: str, known: tuple[str, ...] = ()) -> None:
    """Reject a model that is clearly not an image-generation model.

    Permissive by design — any name carrying an image hint (or unknown to us) is
    allowed and the backend has the final say, so new image models never get
    blocked. Only a name that clearly marks a chat/text/audio/video model is
    rejected up front, turning an opaque provider-side failure into an actionable
    error. ``SHIPIT_ALLOW_UNKNOWN_IMAGE_MODEL`` turns the check off entirely.
    """
    if _allow_unknown_model():
        return
    if not model:
        raise RuntimeError(f"No {backend} image model set (e.g. {', '.join(known) or 'an image model'}).")
    lowered = model.lower()
    if model in known or any(hint in lowered for hint in _IMAGE_MODEL_HINTS):
        return
    for hint in _NON_IMAGE_HINTS:
        if hint in lowered:
            raise RuntimeError(
                f"{model!r} looks like a text/chat/audio/video model, not an "
                f"image-generation model — it can't make images. Point "
                "SHIPIT_IMAGE_MODEL at an image model (e.g. dall-e-3, "
                "vertex_ai/imagegeneration@006), or set "
                "SHIPIT_ALLOW_UNKNOWN_IMAGE_MODEL=1 if you're sure."
            )


# ── built-in backend: OpenAI ──────────────────────────────────────────────


class OpenAIImageProvider:
    """OpenAI Images — ``gpt-image-1`` (default) or ``dall-e-3``."""

    name = "openai"

    def __init__(self, *, model: str = "gpt-image-1") -> None:
        self.model = model

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    #: The OpenAI image models — used to accept an explicit override cleanly.
    known_models = ("gpt-image-1", "dall-e-3", "dall-e-2")

    def generate(self, prompt: str, *, size: str = "1024x1024", **opts: Any) -> bytes:
        model = str(opts.get("model") or self.model)
        validate_image_model(self.name, model, self.known_models)

        from openai import OpenAI  # imported lazily — optional dependency

        client = OpenAI()
        # gpt-image-1 always returns b64_json; dall-e-3 needs it requested.
        kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
        if model.startswith("dall-e"):
            kwargs["response_format"] = "b64_json"
        result = client.images.generate(**kwargs)
        b64 = getattr(result.data[0], "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        # Fallback: a URL came back — fetch it.
        url = getattr(result.data[0], "url", None)
        if not url:
            raise RuntimeError("image backend returned neither b64_json nor a url")
        import urllib.request

        with urllib.request.urlopen(url, timeout=60) as resp:  # nosec B310
            return resp.read()


class LiteLLMImageProvider:
    """Route image generation through LiteLLM — any provider it supports.

    The universal backend: point ``SHIPIT_IMAGE_MODEL`` at a LiteLLM image model
    (``vertex_ai/imagegeneration@006``, ``gemini/imagen-3.0-generate-002``,
    ``dall-e-3``, ``bedrock/...``) and it routes there with that provider's
    credentials. Opt-in — available only when ``SHIPIT_IMAGE_MODEL`` is set, so
    it never shadows a keyed native backend.
    """

    name = "litellm"

    def is_available(self) -> bool:
        if not os.getenv("SHIPIT_IMAGE_MODEL"):
            return False
        try:
            import litellm  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, prompt: str, *, size: str = "1024x1024", **opts: Any) -> bytes:
        model = str(opts.get("model") or os.getenv("SHIPIT_IMAGE_MODEL"))
        validate_image_model(self.name, model)

        import litellm

        result = litellm.image_generation(model=model, prompt=prompt, n=1)
        item = result.data[0]
        b64 = item.get("b64_json") if isinstance(item, dict) else getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if not url:
            raise RuntimeError("litellm image backend returned neither b64_json nor a url")
        import urllib.request

        with urllib.request.urlopen(url, timeout=60) as resp:  # nosec B310
            return resp.read()


# Register the built-in backends at import.
register_image_provider(OpenAIImageProvider())
register_image_provider(LiteLLMImageProvider())
