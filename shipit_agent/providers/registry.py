"""The provider registry — discover, list, and build an LLM by provider name.

Each directory under ``providers/catalog/`` contributes one
:class:`ProviderProfile` (from its ``profile.yaml``) and, optionally, an
imperative ``build()`` (from a sibling ``provider.py``) for providers that need
setup beyond "read an env var and instantiate an adapter" — AWS region
discovery, a package-missing fallback, credential-file resolution.

``load_catalog()`` scans them all once (skip-invalid-with-diagnostic, exactly
like the connector catalog). ``build_provider(name, ...)`` resolves a
name/alias to a profile and calls its builder — the profile's own ``build()``
if it has one, else :func:`generic_build` (require env → resolve model → import
the adapter class → instantiate). Dropping a new ``catalog/<name>/`` directory
adds a provider with no change to this module.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping

from .base import ProviderProfile
from .profiles import parse_profile

logger = logging.getLogger(__name__)

#: A builder turns (profile, config, env) into a live LLM client.
Builder = Callable[[ProviderProfile, dict[str, Any], Mapping[str, str]], Any]

_REGISTRY: dict[str, ProviderProfile] = {}
_ALIASES: dict[str, str] = {}
_BUILDERS: dict[str, Builder] = {}
#: (path, error) for every profile that failed to load — surfaced by a UI/CI.
PROVIDER_DIAGNOSTICS: list[tuple[str, str]] = []
_loaded = False
_load_lock = Lock()

_CATALOG_DIR = Path(__file__).parent / "catalog"


class UnknownProvider(KeyError):
    """No profile matches the requested provider name or alias."""


def register_provider(profile: ProviderProfile, *, build: Builder | None = None) -> ProviderProfile:
    """Add a provider (and optional imperative builder) to the registry.

    Last-writer-wins on name collision, so a user-dropped profile overrides a
    bundled one of the same name.
    """
    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias.lower()] = profile.name
    _BUILDERS[profile.name] = build or generic_build
    return profile


def load_catalog() -> None:
    """Scan ``catalog/<name>/profile.yaml`` and register each provider.

    Idempotent and thread-safe; an invalid profile is skipped and recorded in
    :data:`PROVIDER_DIAGNOSTICS` rather than breaking the whole catalog. Needs
    PyYAML; without it the catalog is empty and a one-line hint is logged (the
    concrete adapters and the factory still work).
    """
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        try:
            import yaml
        except ImportError:
            logger.warning(
                "provider catalog needs PyYAML — install with "
                "'pip install shipit-agent[connectors]'."
            )
            _loaded = True
            return

        for profile_path in sorted(_CATALOG_DIR.glob("*/profile.yaml")):
            try:
                data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
                profile = parse_profile(data)
                build = _load_build(profile_path.parent, profile.name)
                register_provider(profile, build=build)
            except Exception as exc:  # noqa: BLE001 — a bad profile is skipped, never fatal
                PROVIDER_DIAGNOSTICS.append((str(profile_path), str(exc)))
                logger.warning("provider profile %s skipped: %s", profile_path.parent.name, exc)
        _loaded = True


def _load_build(directory: Path, name: str) -> Builder | None:
    """Import ``provider.py``'s ``build`` from a catalog dir, if present."""
    provider_py = directory / "provider.py"
    if not provider_py.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        f"shipit_agent.providers._catalog_{name}", provider_py
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = getattr(module, "build", None)
    return build if callable(build) else None


# ── lookup ───────────────────────────────────────────────────────────────


def get_profile(name: str) -> ProviderProfile | None:
    """Resolve a provider by name or alias (case-insensitive)."""
    load_catalog()
    key = name.strip().lower()
    canonical = _ALIASES.get(key, key)
    return _REGISTRY.get(canonical)


def list_providers() -> list[ProviderProfile]:
    """Every provider profile, alphabetically by name."""
    load_catalog()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def provider_names() -> list[str]:
    """Canonical provider names (not aliases), sorted."""
    load_catalog()
    return sorted(_REGISTRY)


# ── build ────────────────────────────────────────────────────────────────


def build_provider(
    name: str,
    *,
    config: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Turn a provider name/alias into a live LLM client.

    Calls the provider's own ``build()`` when it has one (imperative setup),
    otherwise the generic builder. ``config`` is the caller's settings dict;
    ``env`` defaults to ``os.environ``.
    """
    load_catalog()
    profile = get_profile(name)
    if profile is None:
        known = ", ".join(provider_names())
        raise UnknownProvider(f"Unknown provider '{name}'. Known: {known}")
    # Carry the exact name the caller used so a builder shared by aliases
    # (e.g. shipit/echo) can tell them apart. Never overrides a real setting.
    merged = {"_selected": name.strip().lower(), **dict(config or {})}
    builder = _BUILDERS.get(profile.name, generic_build)
    return builder(profile, merged, env if env is not None else os.environ)


# ── shared helpers used by generic_build and every provider.py ────────────


def require_env_any(
    profile: ProviderProfile, config: Mapping[str, Any], env: Mapping[str, str]
) -> str:
    """Return the first satisfied auth var's value; raise if none is set.

    Matches the historical factory message so callers see no change.
    """
    if not profile.require_env:
        return ""
    for name in profile.require_env:
        value = config.get(name) or env.get(name)
        if value:
            return str(value)
    joined = ", ".join(profile.require_env)
    raise RuntimeError(
        f"Missing environment variable for {profile.name}. Set one of: {joined}"
    )


def resolve_model(
    profile: ProviderProfile, config: Mapping[str, Any], env: Mapping[str, str]
) -> str:
    """Pick the model: config keys → model_env vars → the profile default."""
    for key in profile.model_keys:
        value = config.get(key)
        if value:
            return str(value)
    for var in profile.model_env:
        value = config.get(var) or env.get(var)
        if value:
            return str(value)
    return profile.default_model


def import_adapter(path: str) -> Callable[..., Any]:
    """Import an adapter class from a ``"module.path:ClassName"`` string."""
    module_path, _, cls_name = path.partition(":")
    if not module_path or not cls_name:
        raise ValueError(f"invalid adapter path {path!r} (want 'module:Class')")
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


def generic_build(
    profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]
) -> Any:
    """The default builder: require env → resolve model → instantiate adapter.

    Enough for every provider that just needs a key and a model. Providers with
    imperative setup ship a ``provider.py`` and never reach here.
    """
    require_env_any(profile, config, env)
    model = resolve_model(profile, config, env)
    adapter = import_adapter(profile.adapter)
    return adapter(model=model) if model else adapter()
