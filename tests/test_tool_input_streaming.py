"""Streaming a tool call's arguments as the model writes them."""

from __future__ import annotations

import io
import json

import pytest

from shipit_agent.llms.base import accepts_tool_input_callback
from shipit_agent.models import AgentEvent
from shipit_agent.narrate.grouping import WorkRunAccumulator
from shipit_agent.narrate.renderer import NarratorRenderer


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def started(call_id="1", tool="write_file", field="content"):
    return AgentEvent(type="tool_input_started", message="", payload={
        "call_id": call_id, "tool": tool, "field": field})


def delta(text, call_id="1", tool="write_file"):
    return AgentEvent(type="tool_input_delta", message="", payload={
        "call_id": call_id, "tool": tool, "delta": text})


def called(tool="write_file", call_id="1", **arguments):
    return AgentEvent(type="tool_called", message="", payload={
        "tool": tool, "call_id": call_id, "arguments": arguments})


def _shipped_adapters():
    """Every LLM adapter class shipit ships, discovered rather than listed."""
    import importlib
    import inspect

    found = []
    for module in ("anthropic_adapter", "openai_adapter", "litellm_adapter", "simple"):
        mod = importlib.import_module(f"shipit_agent.llms.{module}")
        for name, obj in vars(mod).items():
            if (
                inspect.isclass(obj)
                and hasattr(obj, "complete")
                and obj.__module__ == mod.__name__
            ):
                found.append((name, obj))
    return found


class TestAdapterCapability:
    """Every adapter we ship, not just the one that was easy to do."""

    @pytest.mark.parametrize(
        "name,cls", _shipped_adapters(), ids=[n for n, _ in _shipped_adapters()]
    )
    def test_every_shipped_adapter_accepts_it(self, name, cls) -> None:
        """Discovered, not hand-listed, so a new adapter cannot silently opt out."""
        assert accepts_tool_input_callback(cls.complete), (
            f"{name} would raise on tool_input_callback"
        )

    def test_the_big_providers_are_covered(self) -> None:
        # Named explicitly so the discovery above can't pass by finding nothing.
        names = {n for n, _ in _shipped_adapters()}
        assert {
            "AnthropicChatLLM", "OpenAIChatLLM", "LiteLLMChatLLM",
            "BedrockChatLLM", "GeminiChatLLM", "VertexAIChatLLM",
            "GroqChatLLM", "TogetherChatLLM", "OllamaChatLLM",
        } <= names

    def test_a_custom_adapter_without_it_degrades_rather_than_breaking(self) -> None:
        """A third-party adapter written before this existed must still work.

        A bare **kwargs does not count as support: some adapters forward it
        verbatim to an inner one, so treating that as opt-in pushes an unknown
        keyword down a level and raises there. That regression shipped, and the
        suite caught it.
        """

        class OldAdapter:
            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, **kwargs):
                return None

        assert not accepts_tool_input_callback(OldAdapter.complete)


class TestAccumulator:
    def test_the_value_accumulates(self) -> None:
        acc = WorkRunAccumulator()
        acc.feed(started())
        acc.feed(delta("def main():\n"))
        acc.feed(delta("    return 0\n"))
        assert acc.writing_preview == "def main():\n    return 0\n"

    def test_it_clears_when_the_call_settles(self) -> None:
        acc = WorkRunAccumulator()
        acc.feed(started())
        acc.feed(delta("partial"))
        acc.feed(called(path="app.py"))
        assert acc.writing_preview == ""

    def test_several_calls_are_tracked_separately(self) -> None:
        acc = WorkRunAccumulator()
        acc.feed(started(call_id="1"))
        acc.feed(delta("first", call_id="1"))
        acc.feed(started(call_id="2"))
        acc.feed(delta("second", call_id="2"))
        assert acc.writing == {"1": "first", "2": "second"}

    def test_these_events_produce_no_rows(self) -> None:
        acc = WorkRunAccumulator()
        acc.feed(started())
        assert acc.feed(delta("x")) == []


class TestLiveRendering:
    def _render(self, events):
        buffer = FakeTTY()
        renderer = NarratorRenderer(file=buffer, style="auto", show_footer=False)
        for event in events:
            renderer.feed(event)
        return buffer.getvalue()

    def test_the_argument_appears_while_it_is_written(self) -> None:
        out = self._render([started(), delta("def login(request):")])
        assert "def login(request):" in out

    def test_only_the_tail_is_shown(self) -> None:
        # A 400-line file would otherwise scroll the transcript away.
        body = "".join(f"line {i}\n" for i in range(200))
        out = self._render([started(), delta(body)])
        assert "line 199" in out
        assert "line 0\n" not in out

    def test_it_is_replaced_by_the_settled_row(self) -> None:
        buffer = FakeTTY()
        renderer = NarratorRenderer(file=buffer, style="auto", show_footer=False)
        renderer.feed(started())
        renderer.feed(delta("temporary preview text"))
        renderer.feed(called(path="app.py"))
        renderer.feed(AgentEvent(type="tool_completed", message="", payload={
            "tool": "write_file", "call_id": "1", "output": "ok"}))
        renderer.feed(AgentEvent(type="run_completed", message="", payload={"output": ""}))
        renderer.close()
        # The live region was rewound; the past-tense row is what remains.
        assert "\033[" in buffer.getvalue()
        assert "Wrote app.py" in buffer.getvalue()

    def test_piped_output_shows_no_preview(self) -> None:
        buffer = io.StringIO()
        renderer = NarratorRenderer(file=buffer, style="plain", show_footer=False)
        renderer.feed(started())
        renderer.feed(delta("preview only makes sense live"))
        renderer.close()
        assert buffer.getvalue() == ""


class TestRuntimeIntegration:
    def test_deltas_become_events_through_the_parser(self) -> None:
        """End to end: raw argument JSON in, decoded field out as events."""
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall
        from shipit_agent.tools.base import ToolOutput

        payload = json.dumps({"path": "app.py", "content": "def main():\n    pass\n"})

        class StreamingLLM:
            model = "claude-opus-5"

            def __init__(self):
                self.n = 0

            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, text_delta_callback=None,
                         tool_input_callback=None):
                self.n += 1
                if self.n == 1:
                    if tool_input_callback is not None:
                        for i in range(0, len(payload), 7):
                            tool_input_callback("c1", "write_file", payload[i:i + 7])
                    return LLMResponse(tool_calls=[
                        ToolCall(name="write_file",
                                 arguments={"path": "app.py", "content": "x"})])
                return LLMResponse(content="done")

        class W:
            name = "write_file"
            description = "w"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "write_file", "parameters": {
                    "properties": {"path": {"type": "string"},
                                   "content": {"type": "string"}}}}}

            def run(self, context, **kwargs):
                return ToolOutput(text="written")

        result = Agent(llm=StreamingLLM(), tools=[W()], auto_use_skills=False,
                       max_iterations=3).run("write it")

        deltas = [e for e in result.events if e.type == "tool_input_delta"]
        assert deltas, "no tool_input_delta events emitted"
        assert "".join(e.payload["delta"] for e in deltas) == "def main():\n    pass\n"
        assert any(e.type == "tool_input_started" for e in result.events)

    def test_a_tool_with_nothing_worth_streaming_emits_nothing(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse

        class L:
            model = "m"

            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, text_delta_callback=None,
                         tool_input_callback=None):
                if tool_input_callback is not None:
                    tool_input_callback("c1", "read_file", '{"path": "a.py"}')
                return LLMResponse(content="done")

        result = Agent(llm=L(), auto_use_skills=False).run("read it")
        assert not [e for e in result.events if e.type == "tool_input_delta"]

    def test_malformed_argument_json_does_not_break_the_run(self) -> None:
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse

        class L:
            model = "m"

            def complete(self, *, messages, tools=None, system_prompt=None,
                         metadata=None, text_delta_callback=None,
                         tool_input_callback=None):
                if tool_input_callback is not None:
                    tool_input_callback("c1", "write_file", "not json at all")
                return LLMResponse(content="survived")

        assert Agent(llm=L(), auto_use_skills=False).run("go").output == "survived"


class TestAnthropicPump:
    def test_it_forwards_text_and_tool_input(self) -> None:
        from shipit_agent.llms.anthropic_adapter import _pump_stream_events

        class E:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        events = [
            E(type="content_block_start", index=0,
              content_block=E(type="tool_use", id="tc1", name="write_file")),
            E(type="content_block_delta", index=0,
              delta=E(type="input_json_delta", partial_json='{"path"')),
            E(type="content_block_delta", index=0,
              delta=E(type="input_json_delta", partial_json=': "a.py"}')),
            E(type="content_block_delta", index=1,
              delta=E(type="text_delta", text="hello")),
            E(type="content_block_stop", index=0),
        ]
        text, tool = [], []
        _pump_stream_events(events, text.append,
                            lambda cid, name, d: tool.append((cid, name, d)))
        assert text == ["hello"]
        assert "".join(d for _, _, d in tool) == '{"path": "a.py"}'
        assert {c for c, _, _ in tool} == {"tc1"}

    def test_a_raising_callback_does_not_kill_the_stream(self) -> None:
        from shipit_agent.llms.anthropic_adapter import _pump_stream_events

        class E:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        events = [
            E(type="content_block_start", index=0,
              content_block=E(type="tool_use", id="tc1", name="write_file")),
            E(type="content_block_delta", index=0,
              delta=E(type="input_json_delta", partial_json="x")),
            E(type="content_block_delta", index=1,
              delta=E(type="text_delta", text="still here")),
        ]
        text = []

        def boom(*_):
            raise RuntimeError("renderer exploded")

        _pump_stream_events(events, text.append, boom)
        assert text == ["still here"]  # a preview failure costs a preview


class TestOpenAIShapedStreams:
    """OpenAI, Bedrock, Gemini, Groq, Together, Ollama all stream this shape."""

    def _fake_stream(self, monkeypatch, fragments):
        """A chat.completions stream that emits tool-argument fragments."""

        class Fn:
            def __init__(self, name=None, arguments=None):
                self.name, self.arguments = name, arguments

        class Frag:
            def __init__(self, index, fn):
                self.index, self.function = index, fn

        class Delta:
            def __init__(self, tool_calls=None):
                self.content = None
                self.reasoning_content = None
                self.tool_calls = tool_calls

        class Choice:
            def __init__(self, delta):
                self.delta = delta
                self.finish_reason = None

        class Chunk:
            def __init__(self, delta):
                self.choices = [Choice(delta)]
                self.usage = None

        chunks = [Chunk(Delta([Frag(0, Fn(name="write_file"))]))]
        chunks += [
            Chunk(Delta([Frag(0, Fn(arguments=fragment))])) for fragment in fragments
        ]

        class Completions:
            def create(self, **kwargs):
                assert kwargs.get("stream") is True
                return iter(chunks)

        class Chat:
            completions = Completions()

        class Client:
            chat = Chat()

        return Client()

    def test_openai_forwards_argument_fragments(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        payload = json.dumps({"path": "app.py", "content": "print(1)\n"})
        fragments = [payload[i:i + 5] for i in range(0, len(payload), 5)]
        client = self._fake_stream(monkeypatch, fragments)

        seen: list[tuple[str, str, str]] = []
        llm = OpenAIChatLLM(model="gpt-4o", api_key="k")
        llm._complete_streaming(
            client, {"model": "gpt-4o", "messages": []}, None,
            lambda cid, name, d: seen.append((cid, name, d)),
        )

        assert seen, "no tool-input fragments forwarded"
        assert {name for _, name, _ in seen} == {"write_file"}
        assert "".join(d for _, _, d in seen) == payload

    def test_fragments_decode_through_the_parser(self, monkeypatch) -> None:
        """The whole chain: provider fragments -> decoded field."""
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM
        from shipit_agent.narrate.json_stream import StreamingToolInputParser

        body = "def main():\n    return 0\n"
        payload = json.dumps({"path": "app.py", "content": body})
        fragments = [payload[i:i + 3] for i in range(0, len(payload), 3)]
        client = self._fake_stream(monkeypatch, fragments)

        parser = StreamingToolInputParser("content")
        OpenAIChatLLM(model="gpt-4o", api_key="k")._complete_streaming(
            client, {"model": "gpt-4o", "messages": []}, None,
            lambda cid, name, d: parser.append(d),
        )
        assert parser.streaming_value == body
        assert parser.prefix_fields == {"path": "app.py"}

    def test_a_raising_callback_does_not_break_the_stream(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        client = self._fake_stream(monkeypatch, ['{"path": "a.py"}'])

        def boom(*_):
            raise RuntimeError("renderer exploded")

        response = OpenAIChatLLM(model="gpt-4o", api_key="k")._complete_streaming(
            client, {"model": "gpt-4o", "messages": []}, None, boom
        )
        assert response.tool_calls[0].name == "write_file"

    def test_callback_can_stop_runaway_tool_arguments(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        client = self._fake_stream(monkeypatch, ["x" * 64] * 100)
        seen = 0

        def stop(*_):
            nonlocal seen
            seen += 1
            return False if seen == 5 else None

        response = OpenAIChatLLM(model="gpt-4o", api_key="k")._complete_streaming(
            client, {"model": "gpt-4o", "messages": []}, None, stop
        )

        assert seen == 5
        assert response.metadata["stream_stopped"] == "tool_argument_guard"

    def test_text_only_streaming_is_unaffected(self, monkeypatch) -> None:
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        client = self._fake_stream(monkeypatch, ['{"path": "a.py"}'])
        response = OpenAIChatLLM(model="gpt-4o", api_key="k")._complete_streaming(
            client, {"model": "gpt-4o", "messages": []}, lambda _t: None, None
        )
        assert response.tool_calls[0].name == "write_file"
