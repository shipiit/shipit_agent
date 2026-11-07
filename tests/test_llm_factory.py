from __future__ import annotations


from shipit_agent.llms import build_llm_from_settings


def test_build_llm_from_settings_supports_bedrock(monkeypatch) -> None:
    # Patch the adapter at its source module: the provider catalog builds each
    # adapter with a late import from there, so this seam works whether the
    # request is served by the catalog or the inline fallback.
    from shipit_agent.llms import litellm_adapter

    class FakeBedrock:
        def __init__(self, model):
            self.model = model

    monkeypatch.setattr(litellm_adapter, "BedrockChatLLM", FakeBedrock)

    llm = build_llm_from_settings(
        {
            "provider": "bedrock",
            "model": "bedrock/custom-model",
            "AWS_REGION_NAME": "us-east-1",
        }
    )
    assert isinstance(llm, FakeBedrock)
    assert llm.model == "bedrock/custom-model"


def test_build_llm_from_settings_supports_openai(monkeypatch) -> None:
    from shipit_agent.llms import openai_adapter

    class FakeOpenAI:
        def __init__(self, model, tool_choice=None):
            self.model = model
            self.tool_choice = tool_choice

    monkeypatch.setattr(openai_adapter, "OpenAIChatLLM", FakeOpenAI)

    llm = build_llm_from_settings(
        {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "OPENAI_API_KEY": "demo-key",
            "tool_choice": "required",
        }
    )
    assert isinstance(llm, FakeOpenAI)
    assert llm.model == "gpt-4.1-mini"
    assert llm.tool_choice == "required"


def test_build_llm_from_settings_falls_back_to_bedrock_when_anthropic_sdk_missing(
    monkeypatch,
) -> None:
    class FakeBedrock:
        def __init__(self, model):
            self.model = model

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    from shipit_agent.llms import anthropic_adapter, litellm_adapter

    monkeypatch.setattr(anthropic_adapter, "AnthropicChatLLM", broken_anthropic)
    monkeypatch.setattr(litellm_adapter, "BedrockChatLLM", FakeBedrock)

    llm = build_llm_from_settings(
        {
            "provider": "anthropic",
            "ANTHROPIC_API_KEY": "demo-key",
            "AWS_REGION_NAME": "us-east-1",
        }
    )
    assert isinstance(llm, FakeBedrock)


def test_build_llm_from_settings_keeps_explicit_anthropic_error(monkeypatch) -> None:
    from shipit_agent.llms import anthropic_adapter

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    monkeypatch.setattr(anthropic_adapter, "AnthropicChatLLM", broken_anthropic)

    try:
        build_llm_from_settings(
            {"ANTHROPIC_API_KEY": "demo-key"},
            provider="anthropic",
        )
    except RuntimeError as exc:
        assert "Install `anthropic`" in str(exc)
    else:
        raise AssertionError("Expected explicit anthropic provider to keep failing")
