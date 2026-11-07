"""Building a model adapter from settings or environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .inline_providers import INLINE_BUILDERS

SUPPORTED_PROVIDERS = (
    "shipit",
    "bedrock",
    "openai",
    "anthropic",
    "gemini",
    "vertex",
    "litellm",
    "groq",
    "together",
    "ollama",
)


def _discover_env_file() -> Path | None:
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        dotenv = candidate / ".env"
        if dotenv.exists():
            return dotenv
    return None


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    """Read ``KEY=value`` pairs from a ``.env`` file, returning what was loaded."""
    env_path = Path(path) if path else _discover_env_file()
    loaded: dict[str, str] = {}
    if env_path is None or not env_path.exists():
        return loaded

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
        loaded[key.strip()] = value
    return loaded


def _normalized_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (settings or {}).items():
        normalized[str(key)] = value
    return normalized


def _apply_settings_to_env(settings: dict[str, Any]) -> None:
    for name in (
        "AWS_REGION_NAME",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "SHIPIT_VERTEX_CREDENTIALS_FILE",
        "VERTEXAI_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEXAI_LOCATION",
        "VERTEX_LOCATION",
        "GOOGLE_CLOUD_LOCATION",
        "SHIPIT_LITELLM_MODEL",
        "SHIPIT_LITELLM_API_KEY",
        "SHIPIT_LITELLM_API_BASE",
        "SHIPIT_LITELLM_CUSTOM_PROVIDER",
        "GROQ_API_KEY",
        "TOGETHERAI_API_KEY",
        "TOGETHER_API_KEY",
        "SHIPIT_OPENAI_TOOL_CHOICE",
    ):
        value = settings.get(name)
        if value:
            os.environ[name] = str(value)


def _build_from_catalog(
    selected: str, config: dict[str, Any], explicit_provider: bool
):
    """Build via the declarative provider catalog, or ``None`` to fall back.

    Returns ``None`` when the catalog is unavailable (no PyYAML) or doesn't know
    ``selected`` — the caller then uses the inline chain. A genuine build error
    (missing key, missing region) propagates, exactly as the inline chain would.
    """
    try:
        from ..providers import build_provider, get_profile
    except Exception:
        return None
    try:
        profile = get_profile(selected)
    except Exception:
        return None
    if profile is None:
        return None
    # The anthropic profile uses this to decide whether a missing `anthropic`
    # package may silently fall back to Bedrock (only when not explicit).
    return build_provider(
        selected, config={**config, "_explicit_provider": explicit_provider}
    )


def build_llm_from_settings(
    settings: dict[str, Any] | None = None,
    *,
    provider: str | None = None,
    load_env: bool = True,
):
    """Construct the model adapter named by *provider* or the settings, with its credentials.
    """
    if load_env:
        load_env_file()

    config = _normalized_settings(settings)
    _apply_settings_to_env(config)
    explicit_provider = provider is not None
    selected = (
        str(
            provider
            or config.get("provider")
            or config.get("llm_provider")
            or os.getenv("SHIPIT_LLM_PROVIDER", "bedrock")
        )
        .strip()
        .lower()
    )

    # Declarative catalog first: a provider is a dropped-in profile directory
    # (providers/catalog/<name>/), so adding one needs no edit here. The inline
    # chain below is the zero-dependency fallback for when the catalog can't
    # load (PyYAML lives in the [connectors] extra) or doesn't know a provider.
    catalog_llm = _build_from_catalog(selected, config, explicit_provider)
    if catalog_llm is not None:
        return catalog_llm

    builder = INLINE_BUILDERS.get(selected)
    if builder is None:
        raise RuntimeError(
            f"Unsupported SHIPIT_LLM_PROVIDER={selected!r}. Supported values: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    try:
        return builder(config)
    except RuntimeError as exc:
        # Without the `anthropic` package, an anthropic default (not one the
        # caller named) quietly uses Bedrock instead.
        if (
            selected != "anthropic"
            or explicit_provider
            or "Install `anthropic`" not in str(exc)
        ):
            raise
        return build_llm_from_settings(
            {"provider": "bedrock", **config},
            provider="bedrock",
            load_env=False,
        )


def build_llm_from_env(provider: str | None = None):
    """Construct a model adapter from environment variables (and a ``.env`` file)."""
    return build_llm_from_settings(provider=provider)
