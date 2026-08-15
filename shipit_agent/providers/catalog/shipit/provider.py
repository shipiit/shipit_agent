"""Build the built-in provider — ``shipit`` (deterministic) or ``echo``.

Two classes, no model, no key: which one depends on the name the caller used,
so this stays imperative rather than a plain ``adapter:`` in the profile.
"""

from __future__ import annotations

from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.simple import ShipitLLM, SimpleEchoLLM

    # The name the caller asked for wins (the profile is shared by both aliases).
    selected = str(config.get("_selected") or profile.name).strip().lower()
    return SimpleEchoLLM() if selected == "echo" else ShipitLLM()
