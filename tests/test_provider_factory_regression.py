"""Regression guard for ``build_llm_from_settings``.

The provider catalog now backs the factory, but the factory's public contract
must not move: every supported provider resolves to the same adapter class and
default model it always did. And because PyYAML lives in an optional extra, the
inline chain is a fallback — this test proves **both** paths produce identical
results, so a deployment without the catalog behaves exactly the same.
"""

from __future__ import annotations

import pytest

from shipit_agent.llms.factory import build_llm_from_settings
from shipit_agent.llms import factory

# The frozen contract, captured from the pre-catalog factory.
BASELINE = {
    "shipit": ("ShipitLLM", None),
    "bedrock": ("BedrockChatLLM", "bedrock/openai.gpt-oss-120b-1:0"),
    "openai": ("OpenAIChatLLM", "gpt-4o-mini"),
    "anthropic": ("AnthropicChatLLM", "claude-3-5-sonnet-latest"),
    "gemini": ("GeminiChatLLM", "gemini/gemini-1.5-pro"),
    "vertex": ("VertexAIChatLLM", "vertex_ai/gemini-1.5-pro"),
    "litellm": ("LiteLLMChatLLM", "openrouter/x"),
    "groq": ("GroqChatLLM", "groq/llama-3.3-70b-versatile"),
    "together": ("TogetherChatLLM", "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo"),
    "ollama": ("OllamaChatLLM", "ollama/llama3.1"),
}


@pytest.fixture
def full_env(monkeypatch):
    for key, value in {
        "OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GEMINI_API_KEY": "k",
        "AWS_REGION_NAME": "us-east-1", "GROQ_API_KEY": "k", "TOGETHER_API_KEY": "k",
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/c.json", "VERTEXAI_PROJECT": "p",
        "VERTEXAI_LOCATION": "us-central1", "SHIPIT_LITELLM_MODEL": "openrouter/x",
    }.items():
        monkeypatch.setenv(key, value)


def test_supported_providers_is_stable():
    assert factory.SUPPORTED_PROVIDERS == (
        "shipit", "bedrock", "openai", "anthropic", "gemini",
        "vertex", "litellm", "groq", "together", "ollama",
    )


@pytest.mark.parametrize("provider", sorted(BASELINE))
def test_catalog_path_matches_baseline(provider, full_env):
    llm = build_llm_from_settings(provider=provider, load_env=False)
    assert (type(llm).__name__, getattr(llm, "model", None)) == BASELINE[provider]


@pytest.mark.parametrize("provider", sorted(BASELINE))
def test_legacy_fallback_matches_baseline(provider, full_env, monkeypatch):
    # Force the catalog off: the inline chain must reproduce the same result.
    monkeypatch.setattr(factory, "_build_from_catalog", lambda *a, **k: None)
    llm = build_llm_from_settings(provider=provider, load_env=False)
    assert (type(llm).__name__, getattr(llm, "model", None)) == BASELINE[provider]


def test_default_provider_is_bedrock(monkeypatch):
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
    monkeypatch.delenv("SHIPIT_LLM_PROVIDER", raising=False)
    llm = build_llm_from_settings(load_env=False)  # no provider → env default
    assert type(llm).__name__ == "BedrockChatLLM"


def test_unsupported_provider_still_errors(monkeypatch):
    # An unknown name is unknown to both the catalog and the inline chain.
    with pytest.raises(RuntimeError, match="Unsupported|Unknown"):
        build_llm_from_settings(provider="totally-unknown", load_env=False)
