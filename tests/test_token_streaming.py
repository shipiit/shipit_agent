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

    def test_streaming_usage_surfaces_automatic_cache_reads(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        usage = ns(
            prompt_tokens=200,
            completion_tokens=2,
            total_tokens=202,
            prompt_tokens_details=ns(cached_tokens=160),
        )
        _install_fake_openai(monkeypatch, [_chunk("ok"), _chunk(None, usage=usage)])
        out = OpenAIChatLLM(model="gpt-5", api_key="k").complete(
            messages=[Message(role="user", content="hi")],
            text_delta_callback=lambda _chunk: None,
        )
        assert out.usage["cache_read_input_tokens"] == 160

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


class ReasoningMarkupLLM:
    def complete(self, *, text_delta_callback=None, **_kwargs):
        chunks = (
            "Visible. <th",
            "ought\n>private scratch",
            "</thought>Final.",
        )
        for chunk in chunks:
            if text_delta_callback:
                text_delta_callback(chunk)
        return LLMResponse(content="".join(chunks))


class RepeatingVisibleLLM:
    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, text_delta_callback=None, **_kwargs):
        self.turn += 1
        if self.turn > 1:
            if text_delta_callback:
                text_delta_callback("Recovered cleanly.")
            return LLMResponse(content="Recovered cleanly.")
        chunks: list[str] = []
        for chunk in ["I am gathering the relevant evidence.\n\n"] + [
            "repeated planning block\n"
        ] * 100:
            chunks.append(chunk)
            if text_delta_callback and text_delta_callback(chunk) is False:
                break
        return LLMResponse(content="".join(chunks))


class RejectedDraftThenToolLLM:
    """A failed prose turn must not poison either the stream or retry context."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, text_delta_callback=None, **_kwargs):
        self.turn += 1
        if self.turn == 1:
            draft = "I will use add now.\n\n" + ("REJECTED-DRAFT " * 100)
            if text_delta_callback:
                text_delta_callback(draft)
            return LLMResponse(content=draft)
        if self.turn == 2:
            assert all(
                "REJECTED-DRAFT" not in message.content for message in messages
            )
            return LLMResponse(
                tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 3})]
            )
        if text_delta_callback:
            text_delta_callback("Verified: 5.")
        return LLMResponse(content="Verified: 5.")


def _add(a: int, b: int, **_ignored) -> str:
    return str(a + b)


class TestStreamRendererAndRunLive:
    def test_rejected_pre_tool_draft_is_not_replayed_or_streamed(self) -> None:
        result = Agent(
            llm=RejectedDraftThenToolLLM(),
            tools=[FunctionTool.from_callable(_add, name="add")],
            auto_use_skills=False,
            max_iterations=4,
        ).run("Use add to calculate 2 + 3")

        streamed = "".join(
            str(event.payload.get("chunk", ""))
            for event in result.events
            if event.type == "text_delta"
        )
        assert result.output == "Verified: 5."
        assert "REJECTED-DRAFT" not in streamed
        assert "Verified: 5." in streamed
        assert any(event.type == "tool_called" for event in result.events)

    def test_runtime_stops_repetitive_visible_stream_and_recovers(self) -> None:
        result = Agent(
            llm=RepeatingVisibleLLM(),
            auto_use_skills=False,
            max_iterations=2,
            pathological_stream_min_chars=256,
        ).run("inspect and report")

        streamed = "".join(
            str(event.payload.get("chunk", ""))
            for event in result.events
            if event.type == "text_delta"
        )
        assert result.output == "Recovered cleanly."
        assert "I am gathering" in streamed
        assert streamed.count("repeated planning block") <= 1
        assert any(
            event.type == "model_output_compacted"
            and event.payload.get("stream_aborted") is True
            for event in result.events
        )

    def test_runtime_never_streams_provider_reasoning_markup(self) -> None:
        result_events = list(
            Agent(
                llm=ReasoningMarkupLLM(),
                auto_use_skills=False,
                max_iterations=1,
            ).stream("answer")
        )
        streamed = "".join(
            str(event.payload.get("chunk", ""))
            for event in result_events
            if event.type == "text_delta"
        )
        completed = next(
            event for event in result_events if event.type == "run_completed"
        )

        assert streamed == "Visible. Final."
        assert completed.payload["output"] == "Visible. Final."
        assert "thought" not in streamed.lower()
        assert "private scratch" not in streamed

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
