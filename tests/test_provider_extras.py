"""Each provider extra installs what that provider's adapter imports."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXTRAS = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
CATALOG = ROOT / "shipit_agent" / "providers" / "catalog"


def _packages(extra: str) -> set[str]:
    return {re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0].lower() for spec in EXTRAS[extra]}


def _adapter(provider: str) -> str:
    return yaml.safe_load((CATALOG / provider / "profile.yaml").read_text())["adapter"]


def test_extras_for_litellm_routed_providers_install_litellm() -> None:
    for extra, provider in {"google": "gemini", "groq": "groq", "together": "together", "ollama": "ollama"}.items():
        assert "litellm_adapter" in _adapter(provider), f"{provider} no longer runs through LiteLLM"
        assert _packages(extra) == {"litellm"}, f"[{extra}] should install litellm, its adapter's only SDK"


def test_direct_sdk_extras_install_their_sdk() -> None:
    assert _packages("openai") == {"openai"}
    assert _packages("anthropic") == {"anthropic"}
    assert _packages("bedrock") == {"boto3"}
    assert _packages("litellm") == {"litellm"}


def test_all_skips_sdks_no_adapter_imports() -> None:
    assert not _packages("all") & {"google-generativeai", "groq", "together", "ollama"}
