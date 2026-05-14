"""Tests for LiteLLMChatLLM streaming via ``text_delta_callback``.

Mocks ``litellm.completion`` to yield a fake streaming response so the test
runs offline. Verifies:

1. When ``text_delta_callback`` is not provided, behaviour is unchanged
   (single non-streaming completion call).
2. When ``text_delta_callback`` is provided, the callback fires for every
   text chunk and the assembled response matches the concatenated chunks.
3. Tool-call deltas streamed across multiple chunks are correctly
   accumulated and emitted as a single ``ToolCall`` in the final
   ``LLMResponse``.
4. The runtime's ``_complete_with_retry`` wires the callback into the
   ``text_delta`` event stream.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM
from shipit_agent.models import Message


# ----------------------------------------------------------------------
# Fakes for litellm response shape (object-attribute style, like a Pydantic
# model). We use SimpleNamespace because litellm responses are pydantic
# models whose .choices[0].delta.content etc. attribute access is what we
# care about — no dict access.
# ----------------------------------------------------------------------
def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def _make_text_chunk(text: str):
    return _ns(
        choices=[_ns(delta=_ns(content=text, tool_calls=None, reasoning_content=None))],
        usage=None,
    )


def _make_tool_chunk(
    index: int,
    *,
    tc_id: str | None = None,
    fn_name: str | None = None,
    fn_args: str | None = None,
):
    fn = _ns(name=fn_name, arguments=fn_args)
    tc_delta = _ns(index=index, id=tc_id, function=fn)
    return _ns(
        choices=[_ns(delta=_ns(content=None, tool_calls=[tc_delta], reasoning_content=None))],
        usage=None,
    )


def _make_usage_chunk(prompt: int, completion: int):
    return _ns(
        choices=[_ns(delta=_ns(content=None, tool_calls=None, reasoning_content=None))],
        usage=_ns(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion),
    )


def _make_nonstream_response(content: str):
    message = _ns(content=content, tool_calls=[], reasoning_content=None)
    return _ns(
        choices=[_ns(message=message)],
        usage=_ns(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


# ----------------------------------------------------------------------
# Module-level patcher: install a fake ``litellm`` module so the adapter's
# ``from litellm import completion`` import resolves to our mock.
# ----------------------------------------------------------------------
@pytest.fixture
def fake_litellm(monkeypatch):
    fake_mod = types.ModuleType("litellm")
    fake_mod.completion = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake_mod)
    return fake_mod


# ======================================================================
# 1. Non-streaming path unchanged when no callback provided
# ======================================================================
def test_complete_without_callback_runs_non_streaming(fake_litellm):
    fake_litellm.completion.return_value = _make_nonstream_response("hello world")

    llm = LiteLLMChatLLM(model="test-model")
    out = llm.complete(messages=[Message(role="user", content="hi")])

    assert out.content == "hello world"
    # Verify stream=True was NOT passed
    call_kwargs = fake_litellm.completion.call_args.kwargs
    assert "stream" not in call_kwargs or call_kwargs.get("stream") is not True


# ======================================================================
# 2. Callback fires for each text chunk and assembled content matches
# ======================================================================
def test_complete_with_callback_streams_text_chunks(fake_litellm):
    chunks = [
        _make_text_chunk("Hello"),
        _make_text_chunk(", "),
        _make_text_chunk("world"),
        _make_text_chunk("!"),
        _make_usage_chunk(prompt=5, completion=4),
    ]
    fake_litellm.completion.return_value = iter(chunks)

    received: list[str] = []
    llm = LiteLLMChatLLM(model="test-model")
    out = llm.complete(
        messages=[Message(role="user", content="hi")],
        text_delta_callback=received.append,
    )

    assert received == ["Hello", ", ", "world", "!"]
    assert out.content == "Hello, world!"
    assert out.metadata.get("streamed") is True
    assert out.usage["prompt_tokens"] == 5
    assert out.usage["completion_tokens"] == 4

    # Verify stream=True was passed this time
    call_kwargs = fake_litellm.completion.call_args.kwargs
    assert call_kwargs.get("stream") is True


# ======================================================================
# 3. Tool-call deltas accumulate correctly across chunks
# ======================================================================
def test_streaming_accumulates_tool_call_deltas(fake_litellm):
    # A typical streaming tool_call arrives split: first chunk has id +
    # function.name, subsequent chunks have function.arguments fragments.
    chunks = [
        _make_text_chunk("Let me search."),
        _make_tool_chunk(0, tc_id="call_abc", fn_name="search_echos"),
        _make_tool_chunk(0, fn_args='{"query": '),
        _make_tool_chunk(0, fn_args='"lockbit'),
        _make_tool_chunk(0, fn_args='"}'),
        _make_usage_chunk(prompt=10, completion=5),
    ]
    fake_litellm.completion.return_value = iter(chunks)

    received: list[str] = []
    llm = LiteLLMChatLLM(model="test-model")
    out = llm.complete(
        messages=[Message(role="user", content="search lockbit")],
        text_delta_callback=received.append,
    )

    assert received == ["Let me search."]
    assert out.content == "Let me search."
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "search_echos"
    assert out.tool_calls[0].arguments == {"query": "lockbit"}


# ======================================================================
# 4. AgentRuntime wires the callback through to ``text_delta`` events
# ======================================================================
def test_runtime_emits_text_delta_events(fake_litellm):
    """Smoke-test that AgentRuntime._complete_with_retry passes the
    callback to the LLM and that callback emits text_delta events on the
    runtime state."""
    from shipit_agent.runtime import AgentRuntime

    chunks = [
        _make_text_chunk("Hi "),
        _make_text_chunk("there"),
        _make_usage_chunk(prompt=3, completion=2),
    ]
    fake_litellm.completion.return_value = iter(chunks)

    llm = LiteLLMChatLLM(model="test-model")
    runtime = AgentRuntime(llm=llm, prompt="be helpful", max_iterations=1)

    # Capture every event emitted during run.
    state, response = runtime.run("say hi")
    text_deltas = [ev for ev in state.events if ev.type == "text_delta"]

    assert len(text_deltas) == 2
    assert text_deltas[0].payload["chunk"] == "Hi "
    assert text_deltas[1].payload["chunk"] == "there"
    assert response.content == "Hi there"


# ======================================================================
# 5. Callback failures do not crash the stream
# ======================================================================
def test_callback_exception_does_not_break_stream(fake_litellm):
    chunks = [
        _make_text_chunk("safe"),
        _make_text_chunk("also safe"),
        _make_usage_chunk(prompt=1, completion=1),
    ]
    fake_litellm.completion.return_value = iter(chunks)

    def bad_callback(_chunk: str) -> None:
        raise RuntimeError("subscriber crashed")

    llm = LiteLLMChatLLM(model="test-model")
    out = llm.complete(
        messages=[Message(role="user", content="hi")],
        text_delta_callback=bad_callback,
    )

    # Stream still drains, response still assembled.
    assert out.content == "safeal so safe" or out.content == "safealso safe" or out.content == "safe" + "also safe"
