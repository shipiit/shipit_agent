"""Without the `anthropic` package, AnthropicChatLLM fails loudly.

It used to answer with gpt-oss-120b on Bedrock instead, silently: a
benchmark of "Claude Sonnet 5.5" was in fact gpt-oss, priced as Claude.
A missing package must never turn into a different provider and model.
"""

from __future__ import annotations

import builtins

import pytest

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM


def test_a_missing_anthropic_package_raises_and_names_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def no_anthropic(name: str, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    monkeypatch.setattr("shipit_agent.llms.litellm_adapter.BedrockChatLLM.complete",
                        lambda *a, **k: pytest.fail("fell back to Bedrock"))
    with pytest.raises(RuntimeError, match="pip install anthropic"):
        AnthropicChatLLM(model="claude-sonnet-5-5").complete(messages=[Message(role="user", content="hi")])


def test_there_is_no_bedrock_fallback_left() -> None:
    assert not hasattr(AnthropicChatLLM, "_fallback_to_bedrock")
