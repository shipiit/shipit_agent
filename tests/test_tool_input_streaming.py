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


class TestAdapterCapability:
    def test_anthropic_opts_in(self) -> None:
        from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM

        assert accepts_tool_input_callback(AnthropicChatLLM.complete)

    @pytest.mark.parametrize("module,name", [
        ("shipit_agent.llms.openai_adapter", "OpenAIChatLLM"),
        ("shipit_agent.llms.litellm_adapter", "LiteLLMChatLLM"),
    ])
    def test_others_degrade_rather_than_break(self, module, name) -> None:
        """A bare **kwargs must not count as support.

        Some adapters forward **kwargs verbatim to an inner adapter; treating
        that as opt-in pushes an unknown keyword one level down and raises
        there instead. This is a real regression that shipped and was caught.
        """
        import importlib

        cls = getattr(importlib.import_module(module), name)
        assert not accepts_tool_input_callback(cls.complete)


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
