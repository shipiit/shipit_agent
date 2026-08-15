"""The provider catalog: profile-per-directory loading, name/alias resolution,
generic vs imperative builders, and the imperative providers' exact behaviour
(Bedrock region discovery, Anthropic package-missing fallback, Vertex credential
resolution, LiteLLM proxy branching).

The catalog is data — one ``profile.yaml`` per ``providers/catalog/<name>/`` —
so these tests double as a schema guard: a profile that stops parsing, or a
provider that forgets its auth env, fails here.
"""

from __future__ import annotations

import pytest

from shipit_agent.providers import (
    ProfileError,
    ProviderProfile,
    build_provider,
    get_profile,
    import_adapter,
    list_providers,
    parse_profile,
    provider_names,
    register_provider,
    require_env_any,
    resolve_model,
)
from shipit_agent.providers import registry as reg


# ── catalog loads cleanly ────────────────────────────────────────────────


def test_every_profile_parses():
    providers = list_providers()
    assert len(providers) >= 10
    assert reg.PROVIDER_DIAGNOSTICS == []


def test_every_catalog_dir_loads():
    """On-disk profile count == loaded count; nothing silently skipped."""
    from pathlib import Path

    on_disk = list((Path(reg.__file__).parent / "catalog").glob("*/profile.yaml"))
    assert len(on_disk) == len(list_providers())


def test_known_providers_present():
    names = set(provider_names())
    for expected in ("openai", "anthropic", "bedrock", "gemini", "vertex",
                     "litellm", "groq", "together", "ollama", "shipit"):
        assert expected in names


def test_aliases_resolve():
    assert get_profile("vertex_ai").name == "vertex"
    assert get_profile("vertexai").name == "vertex"
    assert get_profile("echo").name == "shipit"
    assert get_profile("proxy").name == "litellm"
    assert get_profile("OpenAI").name == "openai"  # case-insensitive


def test_unknown_provider_is_none():
    assert get_profile("not-a-provider") is None


def test_capabilities_flow_through():
    openai = get_profile("openai")
    assert openai.supports_vision and openai.supports_prompt_cache
    assert openai.display_name == "OpenAI"
    assert "gpt-4o" in openai.fallback_models


# ── building each provider (matches the historical factory) ───────────────


ENV = {
    "OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GEMINI_API_KEY": "k",
    "AWS_REGION_NAME": "us-east-1", "GROQ_API_KEY": "k", "TOGETHER_API_KEY": "k",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/c.json", "VERTEXAI_PROJECT": "p",
    "VERTEXAI_LOCATION": "us-central1", "SHIPIT_LITELLM_MODEL": "openrouter/x",
}

EXPECTED = {
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


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_build_provider_matches_expected(name):
    llm = build_provider(name, env=ENV)
    assert type(llm).__name__ == EXPECTED[name][0]
    assert getattr(llm, "model", None) == EXPECTED[name][1]


def test_model_override_via_config():
    llm = build_provider("openai", config={"model": "gpt-4o"}, env=ENV)
    assert llm.model == "gpt-4o"


def test_model_override_via_env_key():
    env = {**ENV, "SHIPIT_GROQ_MODEL": "groq/custom"}
    assert build_provider("groq", env=env).model == "groq/custom"


def test_build_unknown_provider_raises():
    with pytest.raises(reg.UnknownProvider, match="Unknown provider"):
        build_provider("nope", env=ENV)


# ── generic builder: auth gating ──────────────────────────────────────────


def test_generic_missing_key_raises_with_the_env_names():
    with pytest.raises(RuntimeError, match="Missing environment variable for gemini"):
        build_provider("gemini", env={})  # no GEMINI_API_KEY / GOOGLE_API_KEY


def test_generic_accepts_either_of_two_keys():
    # together is usable with either TOGETHERAI_API_KEY or TOGETHER_API_KEY.
    assert build_provider("together", env={"TOGETHERAI_API_KEY": "k"})
    assert build_provider("together", env={"TOGETHER_API_KEY": "k"})


def test_ollama_needs_no_key():
    assert build_provider("ollama", env={}).model == "ollama/llama3.1"


# ── imperative: bedrock region discovery ──────────────────────────────────


def test_bedrock_uses_explicit_region():
    assert build_provider("bedrock", env={"AWS_REGION_NAME": "eu-west-1"})


def test_bedrock_falls_back_to_boto3_region(monkeypatch):
    import boto3

    class FakeSession:
        region_name = "ap-south-1"

    monkeypatch.setattr(boto3.session, "Session", lambda: FakeSession())
    # No region and no profile in env → boto3 discovery supplies one.
    llm = build_provider("bedrock", env={})
    assert type(llm).__name__ == "BedrockChatLLM"


def test_bedrock_errors_when_no_region_anywhere(monkeypatch):
    import boto3

    class FakeSession:
        region_name = None

    monkeypatch.setattr(boto3.session, "Session", lambda: FakeSession())
    with pytest.raises(RuntimeError, match="Bedrock requires"):
        build_provider("bedrock", env={})


# ── imperative: anthropic package-missing fallback ────────────────────────


def test_anthropic_falls_back_to_bedrock_when_package_missing(monkeypatch):
    import shipit_agent.llms.anthropic_adapter as aa

    def _boom(*a, **k):
        raise RuntimeError("Install `anthropic` to use this provider.")

    monkeypatch.setattr(aa, "AnthropicChatLLM", _boom)
    # Not explicit → silently uses Bedrock (region present).
    llm = build_provider("anthropic", config={"_explicit_provider": False},
                         env={"ANTHROPIC_API_KEY": "k", "AWS_REGION_NAME": "us-east-1"})
    assert type(llm).__name__ == "BedrockChatLLM"


def test_anthropic_raises_when_explicit(monkeypatch):
    import shipit_agent.llms.anthropic_adapter as aa

    def _boom(*a, **k):
        raise RuntimeError("Install `anthropic` to use this provider.")

    monkeypatch.setattr(aa, "AnthropicChatLLM", _boom)
    with pytest.raises(RuntimeError, match="Install `anthropic`"):
        build_provider("anthropic", config={"_explicit_provider": True},
                       env={"ANTHROPIC_API_KEY": "k"})


# ── imperative: vertex credential resolution ──────────────────────────────


def test_vertex_requires_credentials():
    with pytest.raises(RuntimeError, match="Missing environment variable for vertex"):
        build_provider("vertex", env={})


def test_vertex_requires_project_and_location():
    with pytest.raises(RuntimeError, match="vertex"):
        build_provider("vertex", env={"GOOGLE_APPLICATION_CREDENTIALS": "/tmp/c.json"})


# ── imperative: litellm proxy branching ───────────────────────────────────


def test_litellm_requires_a_model():
    with pytest.raises(RuntimeError, match="Missing environment variable for litellm"):
        build_provider("litellm", env={})


def test_litellm_proxy_when_api_base_set():
    llm = build_provider("litellm", config={"api_base": "http://localhost:4000"},
                         env={"SHIPIT_LITELLM_MODEL": "openai/gpt-4o"})
    assert type(llm).__name__ == "LiteLLMProxyChatLLM"


# ── profile parsing / validation ──────────────────────────────────────────


def test_parse_rejects_bad_version():
    with pytest.raises(ProfileError, match="profile_version"):
        parse_profile({"profile_version": 2, "name": "x"})


def test_parse_rejects_non_mapping():
    with pytest.raises(ProfileError, match="must be a mapping"):
        parse_profile(["nope"])  # type: ignore[arg-type]


def test_parse_requires_name():
    with pytest.raises(ProfileError, match="missing required field 'name'"):
        parse_profile({"display_name": "X"})


def test_parse_rejects_invalid_name():
    with pytest.raises(ProfileError, match="invalid name"):
        parse_profile({"name": "bad name!"})


def test_parse_rejects_non_mapping_capabilities():
    with pytest.raises(ProfileError, match="capabilities must be a mapping"):
        parse_profile({"name": "x", "capabilities": ["nope"]})


def test_parse_defaults_display_name_from_name():
    p = parse_profile({"name": "acme"})
    assert p.display_name == "Acme"


# ── helpers ────────────────────────────────────────────────────────────────


def test_resolve_model_precedence():
    p = ProviderProfile(name="x", default_model="d",
                        model_keys=["model", "SHIPIT_X_MODEL"], model_env=["SHIPIT_X_MODEL"])
    assert resolve_model(p, {"model": "cfg"}, {"SHIPIT_X_MODEL": "env"}) == "cfg"
    assert resolve_model(p, {}, {"SHIPIT_X_MODEL": "env"}) == "env"
    assert resolve_model(p, {}, {}) == "d"


def test_require_env_any_returns_first_hit():
    p = ProviderProfile(name="x", require_env=["A", "B"])
    assert require_env_any(p, {}, {"B": "v"}) == "v"


def test_import_adapter_rejects_bad_path():
    with pytest.raises(ValueError, match="invalid adapter path"):
        import_adapter("no-colon-here")


def test_import_adapter_loads_class():
    cls = import_adapter("shipit_agent.llms.simple:ShipitLLM")
    assert cls.__name__ == "ShipitLLM"


# ── drop-in override (last-writer-wins) ───────────────────────────────────


def test_profile_needs_key_and_all_names():
    p = ProviderProfile(name="x", aliases=["y", "z"], require_env=["A"])
    assert p.needs_key is True
    assert p.all_names() == ["x", "y", "z"]
    assert ProviderProfile(name="q").needs_key is False


def test_parse_accepts_a_single_alias_string():
    p = parse_profile({"name": "x", "aliases": "solo"})
    assert p.aliases == ["solo"]


def test_bedrock_boto3_failure_is_swallowed_then_errors(monkeypatch):
    import boto3

    def _raise():
        raise RuntimeError("no AWS config")

    monkeypatch.setattr(boto3.session, "Session", _raise)
    with pytest.raises(RuntimeError, match="Bedrock requires"):
        build_provider("bedrock", env={})


def test_litellm_direct_passes_api_key_and_custom_provider():
    llm = build_provider(
        "litellm",
        config={"api_key": "k", "custom_llm_provider": "openai"},
        env={"SHIPIT_LITELLM_MODEL": "some/model"},
    )
    assert type(llm).__name__ == "LiteLLMChatLLM"


def test_registered_provider_overrides_and_builds(monkeypatch):
    saved_reg = dict(reg._REGISTRY)
    saved_builders = dict(reg._BUILDERS)
    saved_aliases = dict(reg._ALIASES)
    try:
        sentinel = object()
        register_provider(
            ProviderProfile(name="openai", display_name="Custom"),
            build=lambda profile, config, env: sentinel,
        )
        assert get_profile("openai").display_name == "Custom"
        assert build_provider("openai", env=ENV) is sentinel
    finally:
        reg._REGISTRY.clear(); reg._REGISTRY.update(saved_reg)
        reg._BUILDERS.clear(); reg._BUILDERS.update(saved_builders)
        reg._ALIASES.clear(); reg._ALIASES.update(saved_aliases)
