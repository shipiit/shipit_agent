"""Each provider extra installs what that provider's adapter imports."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXTRAS = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
CATALOG = ROOT / "shipit_agent" / "providers" / "catalog"
#: LiteLLM 1.106+ imports mcp on every call with tools, but lists it only under its
#: own [mcp] and [proxy] extras, so a plain install fails on an agent's first call.
LITELLM = {"litellm", "mcp"}


def _packages(extra: str) -> set[str]:
    return {re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0].lower() for spec in EXTRAS[extra]}


def _adapter(provider: str) -> str:
    return yaml.safe_load((CATALOG / provider / "profile.yaml").read_text())["adapter"]


def test_extras_for_litellm_routed_providers_install_litellm() -> None:
    for extra, provider in {"google": "gemini", "groq": "groq", "together": "together", "ollama": "ollama"}.items():
        assert "litellm_adapter" in _adapter(provider), f"{provider} no longer runs through LiteLLM"
        assert _packages(extra) == LITELLM, f"[{extra}] should install what its LiteLLM adapter needs"


def test_direct_sdk_extras_install_their_sdk() -> None:
    assert _packages("openai") == {"openai"}
    assert _packages("anthropic") == {"anthropic"}
    assert _packages("bedrock") == {"boto3"}
    assert _packages("litellm") == LITELLM


def test_all_installs_what_litellm_needs() -> None:
    assert LITELLM <= _packages("all")


def test_all_skips_sdks_no_adapter_imports() -> None:
    assert not _packages("all") & {"google-generativeai", "groq", "together", "ollama"}
