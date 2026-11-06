"""Which provider and model the chat uses, and building its LLM."""

from __future__ import annotations

import os
import sys
from typing import Any

from shipit_agent.cli.llm import DEFAULT_MODELS as _CATALOG_DEFAULTS
from shipit_agent.llms.model_defaults import DEFAULT_MODELS

from .style import yellow

#: Environment override per provider, and the fallback for providers the
#: curated catalog does not cover.
#:
#: Defaults come from `llms.model_defaults`, with the CLI catalog in
#: `cli.llm` overlaid below wherever it has its own pick. They used to be
#: written out here and drifted generations apart from `shipit run`.
_PROVIDER_ENV_FALLBACK = {
    "bedrock": ("SHIPIT_BEDROCK_MODEL", "bedrock/openai.gpt-oss-120b-1:0"),
    "openai": ("SHIPIT_OPENAI_MODEL", DEFAULT_MODELS["openai"]),
    "anthropic": ("SHIPIT_ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"]),
    "gemini": ("SHIPIT_GEMINI_MODEL", DEFAULT_MODELS["gemini"]),
    "vertex": ("SHIPIT_VERTEX_MODEL", DEFAULT_MODELS["vertex"]),
    "groq": ("SHIPIT_GROQ_MODEL", "groq/llama-3.3-70b-versatile"),
    "together": (
        "SHIPIT_TOGETHER_MODEL",
        "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
    ),
    "ollama": ("SHIPIT_OLLAMA_MODEL", "ollama/llama3.1"),
    "litellm": ("SHIPIT_LITELLM_MODEL", ""),
}


PROVIDER_MODEL_ENV = {
    provider: (env_var, _CATALOG_DEFAULTS.get(provider, fallback))
    for provider, (env_var, fallback) in _PROVIDER_ENV_FALLBACK.items()
}


PROVIDER_NAMES = tuple(PROVIDER_MODEL_ENV.keys())


def current_provider_name(explicit: str | None = None) -> str:
    """The model provider in use: *explicit*, else the environment, else the default."""
    return (explicit or os.getenv("SHIPIT_LLM_PROVIDER", "bedrock")).strip().lower()


def current_model_name(provider: str) -> str:
    """The model configured for *provider* in the environment, or its default."""
    env_var, default = PROVIDER_MODEL_ENV.get(provider, ("", ""))
    if not env_var:
        return "(n/a)"
    return os.getenv(env_var, default) or "(unset)"


def build_llm(provider: str | None = None) -> Any:
    """Construct the model adapter for *provider* from environment settings."""
    try:
        from examples.run_multi_tool_agent import build_llm_from_env

        return build_llm_from_env(provider)
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(
            yellow(f"[chat] Could not build a real LLM ({exc}); using SimpleEchoLLM.\n")
        )
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()
