"""Build the LiteLLM provider — the universal escape hatch.

Imperative because LiteLLM has no single default model (the model *is* the
routing target, so it is required) and because pointing at a LiteLLM **proxy**
(``api_base`` set) selects a different adapter than direct routing. Both branches
and every env var mirror the factory exactly.
"""

from __future__ import annotations

from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile
from shipit_agent.providers.registry import resolve_model


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM, LiteLLMProxyChatLLM

    model = resolve_model(profile, config, env)
    if not model:
        raise RuntimeError(
            "Missing environment variable for litellm. Set one of: SHIPIT_LITELLM_MODEL"
        )
    api_key = config.get("api_key") or config.get("SHIPIT_LITELLM_API_KEY") or env.get("SHIPIT_LITELLM_API_KEY")
    api_base = config.get("api_base") or config.get("SHIPIT_LITELLM_API_BASE") or env.get("SHIPIT_LITELLM_API_BASE")
    custom_provider = (
        config.get("custom_llm_provider")
        or config.get("SHIPIT_LITELLM_CUSTOM_PROVIDER")
        or env.get("SHIPIT_LITELLM_CUSTOM_PROVIDER")
    )
    if api_base:
        return LiteLLMProxyChatLLM(
            model=model,
            api_base=str(api_base),
            api_key=str(api_key) if api_key else None,
            custom_llm_provider=str(custom_provider or "openai"),
        )
    completion_kwargs: dict[str, Any] = {}
    if api_key:
        completion_kwargs["api_key"] = str(api_key)
    if custom_provider:
        completion_kwargs["custom_llm_provider"] = str(custom_provider)
    return LiteLLMChatLLM(model=model, **completion_kwargs)
