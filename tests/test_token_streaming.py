"""Tests for Claude-Code-style streaming: token deltas from the OpenAI and
Anthropic adapters, the StreamRenderer, and Agent.run_live()."""

from __future__ import annotations

import io
import sys
import types
from types import SimpleNamespace as ns

from shipit_agent import Agent, FunctionTool, StreamRenderer
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.models import AgentEvent, Message


# ── fake OpenAI with real streaming chunks ────────────────────────────
def _chunk(content=None, tool_frags=None, usage=None):
    delta = ns(content=content, reasoning_content=None, tool_calls=tool_frags)
    return ns(choices=[ns(delta=delta)] if content or tool_frags else [], usage=usage)


def _install_fake_openai(monkeypatch, chunks, *, reject_stream_options=False):
    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            if reject_stream_options and "stream_options" in kwargs:
                raise TypeError("stream_options not supported")
            assert kwargs.get("stream") is True
            return iter(chunks)

    fake = types.ModuleType("openai")
    fake.OpenAI = lambda **_kw: ns(chat=ns(completions=_Completions()))
    monkeypatch.setitem(sys.modules, "openai", fake)
    return seen


class TestOpenAIStreaming:
    def test_completion_controls_are_request_not_client_kwargs(
        self, monkeypatch
    ) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        chunks = [_chunk("ok")]
        seen = _install_fake_openai(monkeypatch, chunks)
        out = OpenAIChatLLM(
            model="google.gemma-4-26b-a4b",
            api_key="k",
            max_tokens=16_000,
            temperature=0.3,
        ).complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=lambda _c: None,
        )

        assert out.content == "ok"
        assert seen["max_tokens"] == 16_000
        assert seen["temperature"] == 0.3

    def test_text_deltas_hit_callback_in_order(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        _install_fake_openai(
            monkeypatch,
            [_chunk("Hel"), _chunk("lo"), _chunk(None, usage=ns(
                prompt_tokens=5, completion_tokens=2, total_tokens=7))],
        )
        got: list[str] = []
        out = OpenAIChatLLM(model="gpt-4o-mini", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=got.append,
        )
        assert got == ["Hel", "lo"]
        assert out.content == "Hello"
        assert out.usage["total_tokens"] == 7
        assert out.metadata["streamed"] is True

    def test_tool_call_fragments_stitched_by_index(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        frag1 = ns(index=0, function=ns(name="add", arguments='{"a": '))
        frag2 = ns(index=0, function=ns(name=None, arguments="2}"))
        _install_fake_openai(monkeypatch, [_chunk(tool_frags=[frag1]),
                                           _chunk(tool_frags=[frag2])])
        out = OpenAIChatLLM(model="gpt-4o-mini", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=lambda _c: None,
        )
        assert out.tool_calls[0].name == "add"
        assert out.tool_calls[0].arguments == {"a": 2}

    def test_stream_options_rejection_falls_back(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        _install_fake_openai(
            monkeypatch, [_chunk("ok")], reject_stream_options=True
        )
        out = OpenAIChatLLM(model="gpt-4o-mini", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=lambda _c: None,
        )
        assert out.content == "ok"

    def test_non_stream_fake_degrades_gracefully(self, monkeypatch) -> None:
        """Gateways/fakes that ignore stream=True still work — one delta."""
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        response = ns(choices=[ns(message=ns(
            content="plain", tool_calls=[], reasoning_content=None))], usage=None)

        class _Completions:
            def create(self, **_kwargs):
                return response

        fake = types.ModuleType("openai")
        fake.OpenAI = lambda **_kw: ns(chat=ns(completions=_Completions()))
        monkeypatch.setitem(sys.modules, "openai", fake)

        got: list[str] = []
        out = OpenAIChatLLM(model="gpt-4o-mini", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=got.append,
        )
        assert out.content == "plain"
        assert got == ["plain"]


class TestAnthropicStreaming:
    def test_stream_helper_used_and_deltas_forwarded(self, monkeypatch) -> None:
        from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM

        final = ns(content=[ns(type="text", text="Hello")], usage=None)

        class _Stream:
            text_stream = iter(["Hel", "lo"])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return final

        class _Messages:
            def stream(self, **_kwargs):
                return _Stream()

            def create(self, **_kwargs):
                raise AssertionError("should stream, not create")

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda **_kw: ns(messages=_Messages())
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        got: list[str] = []
        out = AnthropicChatLLM(model="claude-sonnet-4", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=got.append,
        )
        assert got == ["Hel", "lo"]
        assert out.content == "Hello"


# ── StreamRenderer + Agent.run_live ───────────────────────────────────
class DeltaLLM:
    """Streams tokens on turn 2; calls a tool on turn 1."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools=None, text_delta_callback=None, **_kw):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 3})]
            )
        for token in ("The ", "sum ", "is ", "5."):
            if text_delta_callback:
                text_delta_callback(token)
        return LLMResponse(content="The sum is 5.")


def _add(a: int, b: int, **_ignored) -> str:
    return str(a + b)


class TestStreamRendererAndRunLive:
    def test_run_live_interleaves_cards_and_tokens(self) -> None:
        agent = Agent(
            llm=DeltaLLM(),
            tools=[FunctionTool.from_callable(_add, name="add")],
            auto_use_skills=False,
        )
        buf = io.StringIO()
        output = agent.run_live("2+3?", file=buf)
        text = buf.getvalue()
        assert output == "The sum is 5."
        assert "⚙ add(" in text                  # card
        assert "✓" in text                        # completion status
        assert "The sum is 5." in text            # streamed tokens
        assert "✔ done · 1 tool call" in text     # footer
        # tokens streamed BEFORE the footer
        assert text.index("The sum is 5.") < text.index("✔ done")

    def test_renderer_prints_output_when_no_deltas(self) -> None:
        buf = io.StringIO()
        r = StreamRenderer(file=buf)
        r.feed(AgentEvent(type="run_completed", message="",
                          payload={"output": "final answer"}))
        r.close()
        assert "final answer" in buf.getvalue()
        assert "✔ done" in buf.getvalue()

    def test_renderer_breaks_text_line_before_card(self) -> None:
        buf = io.StringIO()
        r = StreamRenderer(file=buf, show_summary=False)
        r.feed(AgentEvent(type="text_delta", message="", payload={"chunk": "thinking"}))
        r.feed(AgentEvent(type="tool_called", message="",
                          payload={"tool": "bash", "arguments": {"command": "ls"}}))
        r.close()
        assert buf.getvalue().startswith("thinking\n⚙ bash(")
