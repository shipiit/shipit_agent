from __future__ import annotations

import builtins

from shipit_agent.llms import build_llm_from_settings
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message


def test_build_llm_from_settings_supports_bedrock(monkeypatch) -> None:
    from shipit_agent.llms import factory as factory_module

    class FakeBedrock:
        def __init__(self, model):
            self.model = model

    monkeypatch.setattr(factory_module, "BedrockChatLLM", FakeBedrock)

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
    from shipit_agent.llms import factory as factory_module

    class FakeOpenAI:
        def __init__(self, model, tool_choice=None):
            self.model = model
            self.tool_choice = tool_choice

    monkeypatch.setattr(factory_module, "OpenAIChatLLM", FakeOpenAI)

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
    from shipit_agent.llms import factory as factory_module

    class FakeBedrock:
        def __init__(self, model):
            self.model = model

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    monkeypatch.setattr(factory_module, "AnthropicChatLLM", broken_anthropic)
    monkeypatch.setattr(factory_module, "BedrockChatLLM", FakeBedrock)

    llm = build_llm_from_settings(
        {
            "provider": "anthropic",
            "ANTHROPIC_API_KEY": "demo-key",
            "AWS_REGION_NAME": "us-east-1",
        }
    )
    assert isinstance(llm, FakeBedrock)


def test_build_llm_from_settings_keeps_explicit_anthropic_error(monkeypatch) -> None:
    from shipit_agent.llms import factory as factory_module

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    monkeypatch.setattr(factory_module, "AnthropicChatLLM", broken_anthropic)

    try:
        build_llm_from_settings(
            {"ANTHROPIC_API_KEY": "demo-key"},
            provider="anthropic",
        )
    except RuntimeError as exc:
        assert "Install `anthropic`" in str(exc)
    else:
        raise AssertionError("Expected explicit anthropic provider to keep failing")


def test_anthropic_adapter_falls_back_to_bedrock_when_sdk_missing(monkeypatch) -> None:
    from shipit_agent.llms import anthropic_adapter as adapter_module
    from shipit_agent.llms import litellm_adapter as litellm_module

    class FakeBedrock:
        def __init__(self, model):
            self.model = model

        def complete(self, **kwargs):
            return LLMResponse(content="ok", metadata={"model": self.model})

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("missing anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(litellm_module, "BedrockChatLLM", FakeBedrock)
    monkeypatch.setenv("SHIPIT_BEDROCK_MODEL", "bedrock/fallback-model")
    monkeypatch.setattr(builtins, "__import__", fake_import)

    llm = adapter_module.AnthropicChatLLM(model="claude-sonnet-4")
    response = llm.complete(messages=[Message(role="user", content="hello")])

    assert response.content == "ok"
    assert response.metadata["provider"] == "bedrock"
    assert response.metadata["fallback_from"] == "anthropic"
