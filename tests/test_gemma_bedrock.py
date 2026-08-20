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

import pytest

import shipit_agent.llms.litellm_adapter as adapter
from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import BedrockChatLLM, BedrockGemmaChatLLM
from shipit_agent.llms.bedrock_token import BEARER_ENV_VARS, BedrockTokenError


def _clear_bearer_env(monkeypatch) -> None:
    """Drop every spelling of the Bedrock API key.

    Without this a developer machine holding a real key would pass these tests
    for the wrong reason — the routing under test would never be exercised.
    """
    for var in BEARER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestGemmaRouting:
    """Gemma 4 rides Bedrock's OpenAI-compatible mantle endpoint, never
    Converse — and always through the OpenAI-adapter shim aimed at the mantle
    URL (`.../openai/v1`), which returns NATIVE structured `tool_calls`.
    LiteLLM's native `bedrock_mantle/` provider is deliberately NOT used: on
    this endpoint it 400s `model '…' isn't supported on this route` for the
    Gemma ids, and (being the Converse-style path) it would surface tool calls
    as prose to be re-parsed. The shim is the whole route, not a fallback."""

    def test_gemma4_routes_through_shim_with_bearer_key(self, monkeypatch) -> None:
        """A Bedrock API key does not switch on the native route — Gemma always
        goes through the shim so tool calls arrive structured."""
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        llm = BedrockChatLLM(model="google.gemma-4-31b")
        assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)
        assert llm.model == "google.gemma-4-31b"

    def test_sigv4_only_env_derives_a_bearer_token(self, monkeypatch) -> None:
        """A SigV4-only environment is no longer a dead end.

        The shim needs a bearer token, and ordinary AWS credentials can produce
        one (a short-term Bedrock API key *is* a SigV4-presigned request). So
        rather than 401ing on the first call, the credentials already present
        are signed into one and handed to the shim delegate.
        """
        _clear_bearer_env(monkeypatch)
        monkeypatch.setattr(
            adapter, "generate_bearer_token", lambda **_: "bedrock-api-key-derived"
        )
        llm = BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1")
        assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)

    def test_no_credentials_at_all_fails_at_construction(self, monkeypatch) -> None:
        """With nothing to authenticate with, say so now rather than at the
        first call — an adapter that builds fine and then 401s is the single
        most confusing shape this failure can take."""
        _clear_bearer_env(monkeypatch)

        def _no_credentials(**_: Any):
            raise BedrockTokenError("No AWS credentials found.")

        monkeypatch.setattr(adapter, "generate_bearer_token", _no_credentials)
        with pytest.raises(RuntimeError, match="AWS_BEARER_TOKEN_BEDROCK"):
            BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1")

    def test_aws_bearer_token_env_var_is_honoured(self, monkeypatch) -> None:
        """AWS documents AWS_BEARER_TOKEN_BEDROCK and the shim reads it, so an
        already-present token must be used as-is — never re-derived by signing
        fresh SigV4 credentials when a valid key is already exported."""
        _clear_bearer_env(monkeypatch)
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key")

        def _must_not_derive(**_: Any):  # pragma: no cover - guards the assert
            raise AssertionError("a token was already available; none should be signed")

        monkeypatch.setattr(adapter, "generate_bearer_token", _must_not_derive)
        llm = BedrockChatLLM(model="google.gemma-4-31b")
        assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)

    @pytest.mark.parametrize(
        "model_id",
        ["google.gemma-4-31b", "gemma4-31b", "gemma_4-31b", "google.gemma-5-31b"],
    )
    def test_mantle_detection_is_not_punctuation_sensitive(
        self, monkeypatch, model_id
    ) -> None:
        """`"gemma-4" in model` sent `gemma4-31b` to Converse, which cannot
        serve it — so the same model worked or failed on how its id was
        punctuated."""
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        llm = BedrockChatLLM(model=model_id)
        routed_to_mantle = llm._mantle_delegate is not None or llm.model.startswith(
            "bedrock_mantle/"
        )
        assert routed_to_mantle, f"{model_id} was not recognised as a mantle model"

    def test_shim_route_is_fully_constructed(self, monkeypatch) -> None:
        """The shim path used to `return` before calling super().__init__, so a
        BedrockChatLLM reporting itself as one lacked attributes every other
        instance has."""
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        _force_shim_path(monkeypatch)
        llm = BedrockChatLLM(model="google.gemma-4-31b", region="us-east-1")
        assert isinstance(llm._mantle_delegate, BedrockGemmaChatLLM)
        assert llm.prompt_caching is False  # mantle is not Anthropic-family
        assert isinstance(llm.completion_kwargs, dict)

    def test_bedrock_prefix_stripped(self, monkeypatch) -> None:
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        _force_shim_path(monkeypatch)
        llm = BedrockChatLLM(model="bedrock/google.gemma-4-e2b", region="us-east-1")
        assert llm._mantle_delegate.model == "google.gemma-4-e2b"
        assert (
            llm._mantle_delegate.client_kwargs["base_url"]
            == "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
        )

    def test_explicit_bedrock_mantle_prefix_is_honoured(self, monkeypatch) -> None:
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-key")
        llm = BedrockChatLLM(model="bedrock_mantle/google.gemma-4-26b-a4b")
        # Even an explicit `bedrock_mantle/` prefix routes through the shim; the
        # prefix is stripped and the bare model id handed to the delegate.
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
