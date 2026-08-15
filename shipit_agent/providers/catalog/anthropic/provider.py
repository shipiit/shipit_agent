"""Build the Anthropic provider.

Imperative for one reason: when the ``anthropic`` package is not installed and
the caller did **not** explicitly ask for Anthropic (they landed here from a
default/env), shipit falls back to Bedrock rather than erroring — the
long-standing factory behaviour. An explicit ``provider="anthropic"`` still
raises, so a deliberate choice is never silently swapped.
"""

from __future__ import annotations

from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile
from shipit_agent.providers.registry import require_env_any, resolve_model


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
    from shipit_agent.providers.registry import build_provider

    require_env_any(profile, config, env)
    try:
        return AnthropicChatLLM(model=resolve_model(profile, config, env))
    except RuntimeError as exc:
        explicit = bool(config.get("_explicit_provider"))
        if explicit or "Install `anthropic`" not in str(exc):
            raise
        # Package missing and Anthropic wasn't explicitly requested → Bedrock.
        return build_provider("bedrock", config=config, env=env)
