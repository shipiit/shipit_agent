"""Gemma on Amazon Bedrock — transparent routing + agentic tool use.

Gemma 4 is served via Bedrock's OpenAI-compatible ``bedrock-mantle`` endpoint
(native function calling), not the Converse API. ``BedrockChatLLM`` detects a
``google.gemma-4-*`` id and transparently routes it there, so users only ever
touch ``BedrockChatLLM``.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace as _ns
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import BedrockChatLLM, BedrockGemmaChatLLM


def _native_mantle() -> bool:
    from shipit_agent.llms.litellm_adapter import _litellm_supports_bedrock_mantle

    return _litellm_supports_bedrock_mantle()


class TestGemmaRouting:
    """Gemma 4 rides Bedrock's OpenAI-compatible mantle endpoint, never
    Converse. Preferred: LiteLLM's native `bedrock_mantle/` provider
    (https://docs.litellm.ai/docs/providers/bedrock_mantle); fallback for
    older LiteLLM installs: the OpenAI-adapter shim aimed at the mantle URL."""

    def test_gemma4_routes_natively_with_bearer_key(self, monkeypatch) -> None:
        """With a Bedrock API key present, LiteLLM's native provider wins."""
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        llm = BedrockChatLLM(model="google.gemma-4-31b")
        if _native_mantle():
            assert llm._mantle_delegate is None
            assert llm.model == "bedrock_mantle/google.gemma-4-31b"
        else:
            assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)

    def test_gemma4_without_bearer_key_uses_the_shim(self, monkeypatch) -> None:
        """SigV4-only environments must not be routed to the bearer-token
        native provider (it 401s — verified live)."""
        monkeypatch.delenv("BEDROCK_MANTLE_API_KEY", raising=False)
        llm = BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1")
        assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)
        assert llm._mantle_delegate.model == "google.gemma-4-31b"
        assert (
            llm._mantle_delegate.client_kwargs["base_url"]
            == "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
        )

    def test_bedrock_prefix_stripped(self, monkeypatch) -> None:
        monkeypatch.delenv("BEDROCK_MANTLE_API_KEY", raising=False)
        llm = BedrockChatLLM(model="bedrock/google.gemma-4-e2b")
        assert llm._mantle_delegate.model == "google.gemma-4-e2b"

    def test_explicit_bedrock_mantle_prefix_is_honoured(self, monkeypatch) -> None:
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        llm = BedrockChatLLM(model="bedrock_mantle/google.gemma-4-26b-a4b")
        if _native_mantle():
            assert llm.model == "bedrock_mantle/google.gemma-4-26b-a4b"
        else:
            assert llm._mantle_delegate.model == "google.gemma-4-26b-a4b"

    def test_non_gemma4_uses_converse(self) -> None:
        llm = BedrockChatLLM(model="bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0")
        assert llm._mantle_delegate is None

    def test_gemma3_uses_converse(self) -> None:
        # Gemma 3 uses the normal Converse path (no mantle routing).
        llm = BedrockChatLLM(model="bedrock/google.gemma-3-27b-it")
        assert llm._mantle_delegate is None

    def test_explicit_class(self) -> None:
        llm = BedrockGemmaChatLLM(model="google.gemma-4-31b", region="us-west-2")
        assert "us-west-2" in llm.client_kwargs["base_url"]


def _install_fake_openai(monkeypatch, *responses) -> None:
    """Inject a fake ``openai`` module returning the given responses in order."""
    calls = {"i": 0}

    class _Completions:
        def create(self, **_kwargs):
            r = responses[min(calls["i"], len(responses) - 1)]
            calls["i"] += 1
            return r

    class _OpenAI:
        def __init__(self, **_kwargs):
            self.chat = _ns(completions=_Completions())

    fake = types.ModuleType("openai")
    fake.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", fake)


def _tool_call_response(name: str, arguments: str):
    msg = _ns(
        content="",
        tool_calls=[_ns(id="c1", function=_ns(name=name, arguments=arguments))],
        reasoning_content=None,
    )
    return _ns(choices=[_ns(message=msg)], usage=None)


def _text_response(text: str):
    msg = _ns(content=text, tool_calls=[], reasoning_content=None)
    return _ns(choices=[_ns(message=msg)], usage=None)


def _force_shim_path(monkeypatch) -> None:
    """Pin these tests to the OpenAI-adapter fallback, which must keep
    working on LiteLLM installs without the native bedrock_mantle provider."""
    import shipit_agent.llms.litellm_adapter as adapter

    monkeypatch.setattr(adapter, "_litellm_supports_bedrock_mantle", lambda: False)


class TestGemmaAgentic:
    def test_gemma4_parses_native_tool_call(self, monkeypatch) -> None:
        _force_shim_path(monkeypatch)
        _install_fake_openai(monkeypatch, _tool_call_response("add", '{"a": 2, "b": 3}'))
        llm = BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1")
        from shipit_agent.models import Message

        resp = llm.complete(
            messages=[Message(role="user", content="add 2 and 3")],
            tools=[{"type": "function", "function": {"name": "add"}}],
        )
        assert resp.tool_calls and resp.tool_calls[0].name == "add"
        assert resp.tool_calls[0].arguments == {"a": 2, "b": 3}

    def test_gemma4_full_agent_loop(self, monkeypatch) -> None:
        _force_shim_path(monkeypatch)
        # Turn 1: model calls the tool. Turn 2: model answers.
        _install_fake_openai(
            monkeypatch,
            _tool_call_response("add", '{"a": 2, "b": 3}'),
            _text_response("The answer is 5."),
        )
        ran: list[str] = []

        def add(a: int, b: int, **_: Any) -> str:
            ran.append("add")
            return str(a + b)

        agent = Agent(
            llm=BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1"),
            tools=[FunctionTool.from_callable(add, name="add")],
            auto_use_skills=False,
        )
        result = agent.run("What is 2 + 3?")
        assert ran == ["add"]  # the tool actually ran — agentic works
        assert "answer is 5" in result.output
