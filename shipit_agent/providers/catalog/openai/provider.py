"""Build the OpenAI provider.

Almost generic, but OpenAI carries an optional ``tool_choice`` resolved from
the caller's settings or ``SHIPIT_OPENAI_TOOL_CHOICE`` — so it gets a tiny
builder instead of a plain ``adapter:`` in the profile.
"""

from __future__ import annotations

from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile
from shipit_agent.providers.registry import require_env_any, resolve_model


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.openai_adapter import OpenAIChatLLM

    require_env_any(profile, config, env)
    tool_choice = (
        config.get("tool_choice")
        or config.get("SHIPIT_OPENAI_TOOL_CHOICE")
        or env.get("SHIPIT_OPENAI_TOOL_CHOICE")
        or None
    )
    return OpenAIChatLLM(model=resolve_model(profile, config, env), tool_choice=tool_choice)
