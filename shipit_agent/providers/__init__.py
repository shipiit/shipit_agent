"""Model providers as declarative profiles.

Each provider is a clean directory under ``catalog/`` — a ``profile.yaml``
(display name, auth env vars, adapter class, default model, capabilities) plus
an optional ``provider.py`` for imperative setup. The registry discovers them,
lets a UI list them, and turns a provider name into a live LLM client.

This layer sits *on top of* the existing adapter classes (``OpenAIChatLLM`` …) —
it makes "which providers exist and how do I build one" data instead of a
hard-coded branch, so a new provider is a dropped-in directory, not a code edit.

    from shipit_agent.providers import list_providers, build_provider
    for p in list_providers():
        print(p.name, p.display_name, "vision" if p.supports_vision else "")
    llm = build_provider("openai", config={"model": "gpt-4o"})
"""

from __future__ import annotations

from .base import ProviderProfile
from .profiles import ProfileError, parse_profile
from .registry import (
    PROVIDER_DIAGNOSTICS,
    UnknownProvider,
    build_provider,
    generic_build,
    get_profile,
    import_adapter,
    list_providers,
    load_catalog,
    provider_names,
    register_provider,
    require_env_any,
    resolve_model,
)

__all__ = [
    "ProviderProfile",
    "ProfileError",
    "parse_profile",
    "PROVIDER_DIAGNOSTICS",
    "UnknownProvider",
    "build_provider",
    "generic_build",
    "get_profile",
    "import_adapter",
    "list_providers",
    "load_catalog",
    "provider_names",
    "register_provider",
    "require_env_any",
    "resolve_model",
]
