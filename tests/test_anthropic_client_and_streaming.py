"""The Anthropic adapter reuses one client and streams when the output can be large.

Building a client per call throws away its connection pool. And the SDK will
not send a very large ``max_tokens`` without streaming, so the adapter streams
whenever the request asks for more than a non-streaming call can safely wait
for, beta endpoint included.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.claude_models import (
    NON_STREAMING_OUTPUT_CAP,
    STREAMING_OUTPUT_CAP,
)

_MESSAGE = types.SimpleNamespace(
    content=[types.SimpleNamespace(type="text", text="ok")],
    usage=None,
    stop_reason="end_turn",
)


class _Stream:
    def __init__(self, sink: dict[str, Any], kwargs: dict[str, Any]) -> None:
        sink["streamed"] = kwargs
        self.text_stream = iter(["o", "k"])

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        return _MESSAGE


class _Messages:
    def __init__(self, sink: dict[str, Any], endpoint: str) -> None:
        self.sink = sink
        self.endpoint = endpoint

    def create(self, **kwargs: Any) -> Any:
        self.sink[f"{self.endpoint}_created"] = kwargs
        return _MESSAGE

    def stream(self, **kwargs: Any) -> _Stream:
        self.sink["endpoint"] = self.endpoint
        return _Stream(self.sink, kwargs)


class _Client:
    def __init__(self, sink: dict[str, Any], **options: Any) -> None:
        self.sink = sink
        self.options = options
        self.messages = _Messages(sink, "ga")
        self.beta = types.SimpleNamespace(messages=_Messages(sink, "beta"))

    def with_options(self, **options: Any) -> "_Client":
        self.sink.setdefault("with_options", []).append(options)
        return self


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sink: dict[str, Any] = {"clients": 0}
    fake = types.ModuleType("anthropic")

    def _anthropic(**options: Any) -> _Client:
        sink["clients"] += 1
        return _Client(sink, **options)

    fake.Anthropic = _anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return sink


def _ask(llm: AnthropicChatLLM, **extra: Any) -> Any:
    return llm.complete(messages=[Message(role="user", content="hi")], **extra)


def test_one_client_serves_every_call(sdk: dict[str, Any]) -> None:
    llm = AnthropicChatLLM(model="claude-opus-5-5")
    _ask(llm)
    _ask(llm)
    assert sdk["clients"] == 1


def test_a_per_call_timeout_uses_the_same_client(sdk: dict[str, Any]) -> None:
    llm = AnthropicChatLLM(model="claude-opus-5-5")
    _ask(llm, timeout=12.0)
    assert sdk["clients"] == 1
    assert sdk["with_options"] == [{"timeout": 12.0}]


def test_a_small_request_is_not_streamed(sdk: dict[str, Any]) -> None:
    _ask(AnthropicChatLLM(model="claude-opus-5-5"))
    assert sdk["ga_created"]["max_tokens"] == NON_STREAMING_OUTPUT_CAP
    assert "streamed" not in sdk


def test_a_large_max_tokens_is_streamed_without_a_callback(sdk: dict[str, Any]) -> None:
    response = _ask(AnthropicChatLLM(model="claude-opus-5-5", max_tokens=100_000))
    assert sdk["streamed"]["max_tokens"] == 100_000
    assert response.content == "ok"


def test_a_streamed_call_gets_room_to_write(sdk: dict[str, Any]) -> None:
    _ask(AnthropicChatLLM(model="claude-opus-5-5"), text_delta_callback=lambda _t: None)
    assert sdk["streamed"]["max_tokens"] == STREAMING_OUTPUT_CAP


def test_streamed_room_never_exceeds_the_model(sdk: dict[str, Any]) -> None:
    _ask(AnthropicChatLLM(model="claude-old-1"), text_delta_callback=lambda _t: None)
    assert sdk["streamed"]["max_tokens"] == 8_192


def test_the_beta_endpoint_streams_too(sdk: dict[str, Any]) -> None:
    llm = AnthropicChatLLM(
        model="claude-opus-5-5",
        context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
    )
    _ask(llm, text_delta_callback=lambda _t: None)
    assert sdk["endpoint"] == "beta"
    assert sdk["streamed"]["betas"]


def test_a_new_sdk_module_gets_a_new_client(sdk: dict[str, Any], monkeypatch) -> None:
    llm = AnthropicChatLLM(model="claude-opus-5-5")
    _ask(llm)
    other = types.ModuleType("anthropic")
    other.Anthropic = lambda **options: _Client({"clients": 0}, **options)
    monkeypatch.setitem(sys.modules, "anthropic", other)
    _ask(llm)
    assert sdk["clients"] == 1
