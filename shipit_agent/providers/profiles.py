"""Parse a provider ``profile.yaml`` into a :class:`ProviderProfile`.

The profile is the declarative, mostly-no-code definition of a model provider —
one per directory under ``catalog/``. This module is the single place that knows
the on-disk shape, so the rest of the system only ever sees a validated
:class:`ProviderProfile`. Invalid profiles raise :class:`ProfileError` with a
clear message; the loader turns that into a skipped-with-diagnostic, never a
crash.

Schema (v1)::

    profile_version: 1
    name: openai
    display_name: OpenAI
    description: GPT-4o and o-series models.
    icon: "🟢"
    aliases: [gpt]
    adapter: shipit_agent.llms.openai_adapter:OpenAIChatLLM
    default_model: gpt-4o-mini
    model_env: [SHIPIT_OPENAI_MODEL]      # env keys that override the default
    require_env: [OPENAI_API_KEY]         # usable if ANY one is set
    capabilities:
      vision: true
      prompt_cache: true
      max_tokens: 0
      fixed_temperature: null
    fallback_models: [gpt-4o]
    signup_url: https://platform.openai.com/api-keys

A provider that needs imperative setup (AWS region discovery, a package-missing
fallback, credential-file resolution) adds a sibling ``provider.py`` exporting
``build(profile, config, env) -> llm``; the profile then carries only metadata.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ProviderProfile

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class ProfileError(ValueError):
    """A profile is missing a required field or has an invalid value."""


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ProfileError(f"missing required field '{key}'")
    return data[key]


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def parse_profile(data: dict[str, Any]) -> ProviderProfile:
    """Validate a profile dict and build a :class:`ProviderProfile`."""
    if not isinstance(data, dict):
        raise ProfileError("profile must be a mapping")
    version = data.get("profile_version", 1)
    if version != 1:
        raise ProfileError(f"unsupported profile_version {version!r} (expected 1)")

    name = str(_require(data, "name")).strip()
    if not _NAME.match(name):
        raise ProfileError(f"invalid name {name!r} (allowed: A-Z a-z 0-9 _ -)")

    caps = data.get("capabilities") or {}
    if not isinstance(caps, dict):
        raise ProfileError("capabilities must be a mapping")
    temp = caps.get("fixed_temperature")

    return ProviderProfile(
        name=name,
        display_name=str(data.get("display_name") or name.title()),
        description=str(data.get("description") or ""),
        aliases=_str_list(data.get("aliases")),
        adapter=str(data.get("adapter") or ""),
        default_model=str(data.get("default_model") or ""),
        model_env=_str_list(data.get("model_env")),
        model_keys=_str_list(data.get("model_keys")) or ["model"],
        require_env=_str_list(data.get("require_env")),
        api_mode=str(data.get("api_mode") or "chat_completions"),
        supports_vision=bool(caps.get("vision", False)),
        supports_prompt_cache=bool(caps.get("prompt_cache", False)),
        default_max_tokens=int(caps.get("max_tokens", 0) or 0),
        fixed_temperature=float(temp) if temp is not None else None,
        fallback_models=_str_list(data.get("fallback_models")),
        signup_url=str(data.get("signup_url") or ""),
        env_help=str(data.get("env_help") or ""),
        icon=str(data.get("icon") or ""),
    )
