"""One provider, one profile.

A :class:`ProviderProfile` is a small, declarative description of a model
provider — its display name, the env var(s) that authenticate it, the adapter
class that talks to it, the default model, and its capabilities (vision, prompt
cache, a fixed-temperature quirk). Each provider is its own clean directory under
``providers/catalog/`` holding a ``profile.yaml`` and — only when the provider
needs imperative setup (AWS region discovery, a package-missing fallback,
multi-env credential resolution) — an optional ``provider.py`` exporting a
``build()`` function.

The profile is the single source of truth the rest of the system reads:
:func:`registry.build_provider` turns a profile into a live LLM client, the
factory resolves a provider name/alias to one, and a UI reads ``display_name`` /
``signup_url`` / capabilities to render a picker. Nothing here imports a provider
SDK or holds a secret — profiles are pure data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProviderProfile:
    """A declarative model-provider definition."""

    #: Catalog key, e.g. ``"openai"``. Lowercase, no spaces.
    name: str
    #: Human label for a picker, e.g. ``"OpenAI"``.
    display_name: str = ""
    #: One line for a catalog card.
    description: str = ""
    #: Alternative names that resolve to this provider (e.g. ``vertex_ai``).
    aliases: list[str] = field(default_factory=list)

    # ── resolution ──────────────────────────────────────────────────────
    #: Dotted path to the adapter class, ``"module.path:ClassName"``. The
    #: generic builder imports and instantiates it with ``model=``; an
    #: imperative provider may ignore this and build in its own ``provider.py``.
    adapter: str = ""
    #: Model used when the caller names none.
    default_model: str = ""
    #: Env var names checked (in order) for a model override before the default.
    model_env: list[str] = field(default_factory=list)
    #: Config/settings keys checked (in order) for a model override — highest
    #: precedence, ahead of ``model_env`` and ``default_model``.
    model_keys: list[str] = field(default_factory=lambda: ["model"])
    #: Auth env var(s); the provider is usable if **any one** is set. Empty
    #: means no key needed (e.g. a local Ollama, the echo provider).
    require_env: list[str] = field(default_factory=list)

    # ── capabilities (metadata for callers / UI / failover) ─────────────
    #: Wire API shape — ``"chat_completions"`` for everything today.
    api_mode: str = "chat_completions"
    #: Provider/model can accept image blocks.
    supports_vision: bool = False
    #: Provider honours a prompt-cache key / implicit prefix cache.
    supports_prompt_cache: bool = False
    #: Default output-token cap (0 = adapter/library default).
    default_max_tokens: int = 0
    #: A provider that rejects a custom temperature pins this value (``None`` =
    #: no constraint). Recorded so callers don't fight the provider.
    fixed_temperature: float | None = None
    #: Ordered fallback model ids for transparent failover (used by a later
    #: failover layer; carried here as data so a profile fully describes itself).
    fallback_models: list[str] = field(default_factory=list)

    # ── presentation / onboarding ───────────────────────────────────────
    #: Where a user gets a key.
    signup_url: str = ""
    #: One line telling a user which env var to set.
    env_help: str = ""
    #: Emoji / short glyph for a catalog card.
    icon: str = ""

    @property
    def needs_key(self) -> bool:
        return bool(self.require_env)

    def all_names(self) -> list[str]:
        """Every string that resolves to this provider — name and aliases."""
        return [self.name, *self.aliases]
