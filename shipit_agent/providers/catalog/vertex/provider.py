"""Build the Google Vertex AI provider.

Imperative because Vertex authenticates with three separate pieces resolved
from several env vars each — a service-account credentials file, a project, and
a location — validated up front so a misconfiguration fails clearly rather than
deep inside the SDK. Mirrors the factory's ``_require_any`` checks exactly.
"""

from __future__ import annotations

from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile
from shipit_agent.providers.registry import resolve_model


def _first(config: Mapping[str, Any], env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = config.get(name) or env.get(name)
        if value:
            return str(value)
    return ""


def _require(config: Mapping[str, Any], env: Mapping[str, str], *names: str) -> None:
    if not _first(config, env, *names):
        raise RuntimeError(
            f"Missing environment variable for vertex. Set one of: {', '.join(names)}"
        )


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.litellm_adapter import VertexAIChatLLM

    _require(config, env, "GOOGLE_APPLICATION_CREDENTIALS", "SHIPIT_VERTEX_CREDENTIALS_FILE")
    credentials_file = _first(
        config, env,
        "service_account_file", "SHIPIT_VERTEX_CREDENTIALS_FILE",
        "GOOGLE_APPLICATION_CREDENTIALS",
    )
    project_id = _first(config, env, "project_id", "VERTEXAI_PROJECT", "GOOGLE_CLOUD_PROJECT")
    location = _first(
        config, env,
        "location", "VERTEXAI_LOCATION", "VERTEX_LOCATION", "GOOGLE_CLOUD_LOCATION",
    )
    _require(config, env, "VERTEXAI_PROJECT", "GOOGLE_CLOUD_PROJECT")
    _require(config, env, "VERTEXAI_LOCATION", "VERTEX_LOCATION", "GOOGLE_CLOUD_LOCATION")

    return VertexAIChatLLM(
        model=resolve_model(profile, config, env),
        service_account_file=credentials_file,
        project_id=project_id,
        location=location,
    )
