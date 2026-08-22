"""Tests for prompt caching across the Anthropic and LiteLLM adapters.

Prompt caching marks the stable request prefix (tool definitions + system
prompt) with ``cache_control: {"type": "ephemeral"}`` breakpoints so
Anthropic / Bedrock-Anthropic / Vertex-Anthropic bill repeated calls' cached
prefix at ~10% of input and serve them faster.

These tests verify:

1. AnthropicChatLLM places cache_control on the last tool + the system block
   when ``prompt_caching=True`` (the default), and omits it when False.
2. AnthropicChatLLM parses ``cache_*_input_tokens`` usage into LLMResponse.usage.
3. LiteLLMChatLLM forwards cache_control on the system message + last tool for
   Anthropic-family models, never mutates the caller's tool list, and omits
   cache_control for non-Anthropic models or when ``prompt_caching=False``.
4. LiteLLMChatLLM parses cache usage tokens into LLMResponse.usage.

The Anthropic adapter is exercised through ``_build_request_kwargs`` (no SDK
mock needed). The LiteLLM adapter follows the existing pattern in
``test_litellm_streaming.py`` — a fake ``litellm`` module whose ``completion``
mock captures the kwargs the adapter sends.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.litellm_adapter import BedrockChatLLM, LiteLLMChatLLM
from shipit_agent.llms.openai_adapter import OpenAIChatLLM
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message
from shipit_agent.runtime import AgentRuntime


# ----------------------------------------------------------------------
# Shared fixtures / helpers
# ----------------------------------------------------------------------
def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


TOOLS = [
    {
        "function": {
            "name": "search",
            "description": "search the web",
            "parameters": {"type": "object", "properties": {}},
        }
    },
    {
        "function": {
            "name": "calc",
            "description": "do math",
            "parameters": {"type": "object", "properties": {}},
        }
    },
]


@pytest.fixture
def fake_litellm(monkeypatch):
    fake_mod = types.ModuleType("litellm")
    fake_mod.completion = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake_mod)
    return fake_mod


def _make_nonstream_response(
    content: str = "ok",
    *,
    cache_read: int = 0,
    cache_creation: int = 0,
):
    message = _ns(content=content, tool_calls=[], reasoning_content=None)
    usage = _ns(
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )
    return _ns(choices=[_ns(message=message)], usage=usage)


# ======================================================================
# Anthropic adapter — request building
# ======================================================================
class TestAnthropicCacheRequest:
    def test_cache_control_on_last_tool(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=TOOLS,
            system_prompt="You are helpful.",
        )
        anthropic_tools = kwargs["tools"]
        # Only the LAST tool carries the breakpoint (caches whole array).
        assert "cache_control" not in anthropic_tools[0]
        assert anthropic_tools[-1]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_on_system_block(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt="You are helpful.",
        )
        system = kwargs["system"]
        # String system prompt promoted to a list of blocks with a breakpoint.
        assert isinstance(system, list)
        assert system[-1]["type"] == "text"
        assert system[-1]["text"] == "You are helpful."
        assert system[-1]["cache_control"] == {"type": "ephemeral"}

    def test_empty_system_not_promoted(self) -> None:
        """An empty/None system prompt stays a bare string (no cache block)."""
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert kwargs["system"] == ""

    def test_disabled_has_no_cache_control(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=TOOLS,
            system_prompt="You are helpful.",
        )
        # System stays a plain string; no tool carries cache_control.
        assert kwargs["system"] == "You are helpful."
        assert all("cache_control" not in t for t in kwargs["tools"])

    def test_cache_control_on_message_prefix(self) -> None:
        """The last message block carries the third breakpoint, so the
        conversation prefix (the growing part of an agent run) is cached."""
        llm = AnthropicChatLLM(model="claude-sonnet-4")
        kwargs = llm._build_request_kwargs(
            messages=[
                Message(role="user", content="first"),
                Message(role="assistant", content="thinking"),
                Message(role="user", content="second"),
            ],
            tools=TOOLS,
            system_prompt="You are helpful.",
        )
        sent_messages = kwargs["messages"]
        last_content = sent_messages[-1]["content"]
        assert isinstance(last_content, list)
        assert last_content[-1]["cache_control"] == {"type": "ephemeral"}
        # Only the LAST message carries it.
        for msg in sent_messages[:-1]:
            content = msg["content"]
            if isinstance(content, list):
                assert all("cache_control" not in b for b in content)

    def test_message_prefix_untouched_when_disabled(self) -> None:
        llm = AnthropicChatLLM(model="claude-sonnet-4", prompt_caching=False)
        kwargs = llm._build_request_kwargs(
            messages=[Message(role="user", content="hi")],
            tools=None,
            system_prompt=None,
        )
        assert kwargs["messages"][-1]["content"] == "hi"


# ======================================================================
# Anthropic adapter — usage parsing
# ======================================================================
class TestAnthropicCacheUsage:
    def test_usage_includes_cache_tokens(self, monkeypatch) -> None:
        fake_anthropic = types.ModuleType("anthropic")

        usage = _ns(
            input_tokens=100,
            output_tokens=40,
            cache_read_input_tokens=512,
            cache_creation_input_tokens=256,
        )
        response = _ns(
            content=[_ns(type="text", text="hello")],
            usage=usage,
        )

        class _Messages:
            def create(self, **_kwargs):
                return response

        class _Client:
            def __init__(self, **_kwargs):
                self.messages = _Messages()

        fake_anthropic.Anthropic = _Client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

        llm = AnthropicChatLLM(model="claude-sonnet-4")
        out = llm.complete(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
        )
        assert out.usage["prompt_tokens"] == 100
        assert out.usage["completion_tokens"] == 40
        assert out.usage["cache_read_input_tokens"] == 512
        assert out.usage["cache_creation_input_tokens"] == 256


# ======================================================================
# LiteLLM adapter — request building (Anthropic-family path)
# ======================================================================
class TestLiteLLMCacheRequest:
    def test_cache_control_on_system_message_and_last_tool(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response()

        llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-4")
        llm.complete(
            messages=[
                Message(role="system", content="You are helpful."),
                Message(role="user", content="hi"),
            ],
            tools=TOOLS,
        )

        sent = fake_litellm.completion.call_args.kwargs
        # System message content promoted to a list with a cache breakpoint.
        system_msg = next(m for m in sent["messages"] if m["role"] == "system")
        assert isinstance(system_msg["content"], list)
        assert system_msg["content"][-1]["cache_control"] == {"type": "ephemeral"}
        # Last tool carries the breakpoint; first does not.
        assert "cache_control" not in sent["tools"][0]
        assert sent["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_on_last_message_prefix(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response()

        llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-4")
        llm.complete(
            messages=[
                Message(role="system", content="You are helpful."),
                Message(role="user", content="first"),
                Message(role="user", content="second"),
            ],
            tools=TOOLS,
        )

        sent = fake_litellm.completion.call_args.kwargs
        last_msg = sent["messages"][-1]
        assert isinstance(last_msg["content"], list)
        assert last_msg["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_does_not_mutate_caller_tools(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response()
        tools = [dict(t) for t in TOOLS]
        before = [dict(t) for t in tools]

        llm = LiteLLMChatLLM(model="bedrock/anthropic.claude-sonnet-4-20250514-v1:0")
        llm.complete(messages=[Message(role="user", content="hi")], tools=tools)

        # The caller's tool list is untouched (no injected cache_control).
        assert tools == before
        assert all("cache_control" not in t for t in tools)

    def test_non_anthropic_model_has_no_cache_control(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response()

        llm = LiteLLMChatLLM(model="gpt-4o")
        llm.complete(
            messages=[
                Message(role="system", content="You are helpful."),
                Message(role="user", content="hi"),
            ],
            tools=TOOLS,
        )

        sent = fake_litellm.completion.call_args.kwargs
        system_msg = next(m for m in sent["messages"] if m["role"] == "system")
        # System content stays a plain string; no tool gets a breakpoint.
        assert system_msg["content"] == "You are helpful."
        assert all("cache_control" not in t for t in sent["tools"])

    def test_disabled_has_no_cache_control(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response()

        llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-4", prompt_caching=False)
        llm.complete(
            messages=[
                Message(role="system", content="You are helpful."),
                Message(role="user", content="hi"),
            ],
            tools=TOOLS,
        )

        sent = fake_litellm.completion.call_args.kwargs
        system_msg = next(m for m in sent["messages"] if m["role"] == "system")
        assert system_msg["content"] == "You are helpful."
        assert all("cache_control" not in t for t in sent["tools"])

    def test_bedrock_subclass_forwards_prompt_caching_flag(self, fake_litellm) -> None:
        """The keyword-only flag survives the BedrockChatLLM **kwargs hop."""
        fake_litellm.completion.return_value = _make_nonstream_response()

        llm = BedrockChatLLM(
            model="bedrock/anthropic.claude-sonnet-4-20250514-v1:0",
            prompt_caching=False,
        )
        assert llm.prompt_caching is False
        llm.complete(
            messages=[Message(role="system", content="sys")],
            tools=TOOLS,
        )
        sent = fake_litellm.completion.call_args.kwargs
        assert all("cache_control" not in t for t in sent["tools"])


# ======================================================================
# LiteLLM adapter — usage parsing
# ======================================================================
class TestLiteLLMCacheUsage:
    def test_usage_includes_cache_tokens(self, fake_litellm) -> None:
        fake_litellm.completion.return_value = _make_nonstream_response(
            cache_read=128, cache_creation=64
        )

        llm = LiteLLMChatLLM(model="anthropic/claude-sonnet-4")
        out = llm.complete(messages=[Message(role="user", content="hi")])

        assert out.usage["cache_read_input_tokens"] == 128
        assert out.usage["cache_creation_input_tokens"] == 64

    def test_openai_style_cached_tokens(self, fake_litellm) -> None:
        """OpenAI shape: usage.prompt_tokens_details.cached_tokens."""
        message = _ns(content="ok", tool_calls=[], reasoning_content=None)
        usage = _ns(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            prompt_tokens_details=_ns(cached_tokens=77),
        )
        fake_litellm.completion.return_value = _ns(
            choices=[_ns(message=message)], usage=usage
        )

        llm = LiteLLMChatLLM(model="gpt-4o")
        out = llm.complete(messages=[Message(role="user", content="hi")])
        assert out.usage["cache_read_input_tokens"] == 77


# ======================================================================
# OpenAI adapter — cross-provider automatic caching
# ======================================================================
class TestOpenAICacheUsage:
    """OpenAI does *automatic* prompt caching (no cache_control breakpoints).

    The adapter surfaces the cached-prompt portion under the same
    ``cache_read_input_tokens`` key the Anthropic/Bedrock adapters use, so the
    CostTracker bills cache reads cheaper for OpenAI/OpenAI-compatible providers
    too. We inject a fake ``openai`` module whose ``OpenAI`` client returns a
    response whose ``usage.prompt_tokens_details.cached_tokens`` is set.
    """

    def test_openai_surfaces_cached_tokens(self, monkeypatch) -> None:
        message = _ns(content="ok", tool_calls=[], reasoning_content=None)
        usage = _ns(
            prompt_tokens=200,
            completion_tokens=40,
            total_tokens=240,
            # OpenAI's automatic-cache shape.
            prompt_tokens_details=_ns(cached_tokens=160),
            completion_tokens_details=None,
        )
        response = _ns(choices=[_ns(message=message)], usage=usage)

        class _Completions:
            def create(self, **_kwargs):
                return response

        class _Chat:
            def __init__(self):
                self.completions = _Completions()

        class _OpenAI:
            def __init__(self, **_kwargs):
                self.chat = _Chat()

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = _OpenAI
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        llm = OpenAIChatLLM(model="gpt-4o")
        out = llm.complete(messages=[Message(role="user", content="hi")])

        assert out.usage["prompt_tokens"] == 200
        assert out.usage["completion_tokens"] == 40
        # The automatic-cache portion is surfaced under the shared key.
        assert out.usage["cache_read_input_tokens"] == 160


def test_runtime_accumulates_cache_usage_in_run_totals() -> None:
    class CachedLLM:
        model = "cached"

        def complete(self, **_kwargs):
            return LLMResponse(
                content="done",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cache_read_input_tokens": 80,
                    "cache_creation_input_tokens": 10,
                },
            )

    state, _ = AgentRuntime(llm=CachedLLM(), prompt="p").run("go")
    completed = next(event for event in state.events if event.type == "run_completed")
    usage = completed.payload["usage"]

    assert usage["cache_read_input_tokens"] == 80
    assert usage["cache_creation_input_tokens"] == 10
    assert len([event for event in state.events if event.type == "usage_tick"]) == 1

    summary = next(event for event in state.events if event.type == "run_summary")
    assert summary.payload["cache"] == {
        "read_input_tokens": 80,
        "creation_input_tokens": 10,
        "eligible_input_tokens": 180,
        "hit_ratio": 0.4444,
    }
