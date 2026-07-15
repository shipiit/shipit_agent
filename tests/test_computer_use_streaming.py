"""Tests for ComputerUseAgent.stream() — live events from the browser loop."""

from __future__ import annotations

import io

from shipit_agent import StreamRenderer
from shipit_agent.computer_use import ComputerUseAgent, MockBrowserSession
from shipit_agent.llms.base import LLMResponse


class ScriptedVisionLLM:
    """Emits scripted ACTION lines, then DONE."""

    def __init__(self, actions: list[str]) -> None:
        self._actions = iter(actions)

    def complete(self, *, messages, **_kw) -> LLMResponse:
        return LLMResponse(content=next(self._actions))


def _agent(actions: list[str], max_iterations: int = 5) -> ComputerUseAgent:
    return ComputerUseAgent(
        llm=ScriptedVisionLLM(actions),
        browser=MockBrowserSession(),
        goal="test the stream",
        max_iterations=max_iterations,
    )


class TestStreamEvents:
    def test_event_sequence_and_result(self) -> None:
        agent = _agent([
            "ACTION: navigate https://example.com",
            "ACTION: click 10,20",
            "ACTION: done Found it.",
        ])
        events = []
        gen = agent.stream()
        while True:
            try:
                events.append(next(gen))
            except StopIteration as stop:
                result = stop.value
                break

        types = [e.type for e in events]
        assert types[0] == "run_started"
        assert types.count("tool_called") == 2
        assert types.count("tool_completed") == 2
        assert types[-1] == "run_completed"
        assert result.status == "done"
        assert result.final_text == "Found it."

        nav = next(e for e in events if e.type == "tool_called")
        assert nav.payload["tool"] == "browser.navigate"
        done = next(e for e in events if e.type == "tool_completed")
        assert done.payload["call_id"] == nav.payload["call_id"]
        assert done.payload["duration_ms"] >= 0
        assert "navigated to" in done.payload["output"]

    def test_run_still_returns_same_result(self) -> None:
        agent = _agent(["ACTION: done quick"])
        result = agent.run()
        assert result.status == "done"
        assert result.final_text == "quick"
        assert result.iterations == 1

    def test_max_iterations_emits_run_completed(self) -> None:
        agent = _agent(["ACTION: screenshot"] * 3, max_iterations=2)
        events = list(agent.stream())
        assert events[-1].type == "run_completed"
        assert events[-1].payload["status"] == "max_iterations"

    def test_stream_renders_as_tool_cards(self) -> None:
        agent = _agent([
            "ACTION: navigate https://example.com",
            "ACTION: done All set.",
        ])
        buf = io.StringIO()
        renderer = StreamRenderer(file=buf, style="plain")
        for event in agent.stream():
            renderer.feed(event)
        renderer.close()
        text = buf.getvalue()
        assert "⚙ browser.navigate(" in text
        assert "navigated to https://example.com" in text
        assert "All set." in text
        assert "✔ done · 1 tool call" in text


class TestQuotedActionParsing:
    """Regression: models emit quoted URLs → Playwright 'invalid URL'."""

    def test_navigate_strips_quotes(self) -> None:
        from shipit_agent.computer_use import parse_action

        for raw in (
            'ACTION: navigate "https://www.google.com/flights"',
            "ACTION: navigate 'https://www.google.com/flights'",
            'ACTION: navigate ""https://www.google.com/flights""',
            'ACTION: navigate url="https://www.google.com/flights"',
            'ACTION: navigate URL=https://www.google.com/flights',
        ):
            action = parse_action(raw)
            assert action.args["url"] == "https://www.google.com/flights", raw

    def test_key_and_type_strip_quotes(self) -> None:
        from shipit_agent.computer_use import parse_action

        assert parse_action('ACTION: key "Enter"').args["key"] == "Enter"
        assert parse_action("ACTION: type 'hello world'").args["text"] == "hello world"

    def test_anthropic_block_url_stripped(self) -> None:
        from shipit_agent.computer_use import parse_action

        action = parse_action(
            {"type": "tool_use", "name": "computer",
             "input": {"action": "navigate", "url": '"https://kayak.com"'}}
        )
        assert action.args["url"] == "https://kayak.com"
