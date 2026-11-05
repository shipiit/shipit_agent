"""More providers through LiteLLM, and one source for every default model.

Each provider is a catalog profile. A provider whose model names change too
often to pin ships no default and asks for one by name instead of failing on
a missing argument; every default lives in ``llms.model_defaults`` and the
catalog must agree with it, so retired models cannot linger in one copy.
"""

from __future__ import annotations

import pytest

from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM
from shipit_agent.llms.model_defaults import DEFAULT_MODELS
from shipit_agent.providers import build_provider, get_profile
from shipit_agent.providers.registry import load_catalog

#: provider -> (key variable, route prefix of its models)
NEW_PROVIDERS = {
    "mistral": ("MISTRAL_API_KEY", "mistral/"),
    "openrouter": ("OPENROUTER_API_KEY", "openrouter/"),
    "xai": ("XAI_API_KEY", "xai/"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek/"),
    "azure": ("AZURE_API_KEY", "azure/"),
    "fireworks": ("FIREWORKS_AI_API_KEY", "fireworks_ai/"),
    "perplexity": ("PERPLEXITYAI_API_KEY", "perplexity/"),
    "cerebras": ("CEREBRAS_API_KEY", "cerebras/"),
    "cohere": ("COHERE_API_KEY", "cohere/"),
}


@pytest.mark.parametrize("name", sorted(NEW_PROVIDERS))
def test_each_new_provider_is_in_the_catalog(name: str) -> None:
    load_catalog()
    profile = get_profile(name)
    assert profile is not None
    assert profile.adapter.endswith(":LiteLLMChatLLM")
    assert NEW_PROVIDERS[name][0] in profile.require_env


@pytest.mark.parametrize("name", sorted(NEW_PROVIDERS))
def test_each_builds_with_its_key_and_a_model(name: str) -> None:
    key, prefix = NEW_PROVIDERS[name]
    llm = build_provider(name, config={"model": f"{prefix}some-model"}, env={key: "k"})
    assert isinstance(llm, LiteLLMChatLLM)
    assert llm.model == f"{prefix}some-model"


@pytest.mark.parametrize("name", sorted(NEW_PROVIDERS))
def test_a_missing_key_is_named(name: str) -> None:
    with pytest.raises(RuntimeError, match=NEW_PROVIDERS[name][0]):
        build_provider(name, config={"model": "x"}, env={})


def test_a_provider_without_a_default_asks_for_a_model_by_name() -> None:
    profile = get_profile("xai")
    assert profile is not None and not profile.default_model
    with pytest.raises(RuntimeError, match="SHIPIT_XAI_MODEL"):
        build_provider("xai", config={}, env={"XAI_API_KEY": "k"})


def test_a_model_from_the_environment_is_used() -> None:
    llm = build_provider(
        "xai", config={}, env={"XAI_API_KEY": "k", "SHIPIT_XAI_MODEL": "xai/grok-x"}
    )
    assert llm.model == "xai/grok-x"


def test_the_catalog_and_the_code_agree_on_every_default() -> None:
    load_catalog()
    for name, model in DEFAULT_MODELS.items():
        profile = get_profile(name)
        assert profile is not None, name
        assert profile.default_model == model, name


@pytest.mark.parametrize(
    "retired", ["claude-3-5-sonnet-latest", "gemini-1.5-pro", "gemini-2.0-flash"]
)
def test_no_default_is_a_retired_model(retired: str) -> None:
    assert not any(retired in model for model in DEFAULT_MODELS.values())


def test_anthropic_defaults_to_the_current_opus() -> None:
    assert DEFAULT_MODELS["anthropic"] == "claude-opus-5-5"
