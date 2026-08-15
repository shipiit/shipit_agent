"""Build the Amazon Bedrock provider.

Imperative because Bedrock needs a region and shipit discovers it the way the
AWS SDK does when no env var is set: fall back to a ``boto3`` session's resolved
region (from ``~/.aws/config`` / instance metadata), and only then error. This
mirrors the long-standing factory behaviour exactly.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from shipit_agent.providers.base import ProviderProfile
from shipit_agent.providers.registry import resolve_model


def build(profile: ProviderProfile, config: dict[str, Any], env: Mapping[str, str]) -> Any:
    from shipit_agent.llms.litellm_adapter import BedrockChatLLM

    region = (
        config.get("AWS_REGION_NAME")
        or config.get("AWS_DEFAULT_REGION")
        or env.get("AWS_REGION_NAME")
        or env.get("AWS_DEFAULT_REGION")
    )
    if not region and not (config.get("AWS_PROFILE") or env.get("AWS_PROFILE")):
        try:
            import boto3  # type: ignore

            session = boto3.session.Session()
            region = session.region_name
            if region:
                os.environ["AWS_REGION_NAME"] = str(region)
                os.environ.setdefault("AWS_DEFAULT_REGION", str(region))
        except Exception:
            region = None
        if not region:
            raise RuntimeError(
                "Bedrock requires AWS_REGION_NAME or AWS_DEFAULT_REGION, or an "
                "AWS_PROFILE configured locally (or a default region in ~/.aws/config)."
            )
    return BedrockChatLLM(model=resolve_model(profile, config, env))
