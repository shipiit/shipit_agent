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
_PREFERENCE = ("openai", "fal", "openrouter")


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


# ── built-in backend: OpenAI ──────────────────────────────────────────────


class OpenAIImageProvider:
    """OpenAI Images — ``gpt-image-1`` (default) or ``dall-e-3``."""

    name = "openai"

    def __init__(self, *, model: str = "gpt-image-1") -> None:
        self.model = model

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def generate(self, prompt: str, *, size: str = "1024x1024", **opts: Any) -> bytes:
        from openai import OpenAI  # imported lazily — optional dependency

        model = str(opts.get("model") or self.model)
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


# Register the built-in backend at import.
register_image_provider(OpenAIImageProvider())
