"""Tests for ComputerUseAgent — screenshot → reason → act loop.

≥10 tests per public surface:
- ``parse_action``               → 14 (Anthropic native + plain text + edge cases)
- ``MockBrowserSession``         → 10
- ``ComputerUseAgent.run``       → 12
- public-import surface          → 4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.computer_use import (
    ActionKind,
    ComputerUseAgent,
    ComputerUseResult,
    MockBrowserSession,
    parse_action,
)


# ---------------------------------------------------------------------------
# Fixture LLMs
# ---------------------------------------------------------------------------


@dataclass
class ScriptedLLM:
    """LLM that returns canned text replies in order."""

    replies: list[str] = field(default_factory=list)
    received: list[list[dict[str, Any]]] = field(default_factory=list)
    _i: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
        self.received.append(list(messages))
        if self._i >= len(self.replies):
            raise RuntimeError("ScriptedLLM exhausted")
        text = self.replies[self._i]
        self._i += 1
        return text


@dataclass
class FailingLLM:
    def complete(self, **_: Any) -> str:
        raise RuntimeError("api down")


# ===========================================================================
# parse_action — Anthropic native (≥6 tests)
# ===========================================================================


class TestParseActionAnthropicNative:
    def test_click_with_coordinate(self) -> None:
        block = {
            "type": "tool_use",
            "name": "computer",
            "input": {"action": "left_click", "coordinate": [120, 240]},
        }
        a = parse_action(block)
        assert a.kind == ActionKind.CLICK
        assert a.args == {"x": 120, "y": 240}

    def test_click_with_x_y_keys(self) -> None:
        block = {
            "type": "tool_use",
            "name": "computer",
            "input": {"action": "click", "x": 50, "y": 60},
        }
        assert parse_action(block).args == {"x": 50, "y": 60}

    def test_type(self) -> None:
        a = parse_action(
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "type", "text": "hello"},
            }
        )
        assert a.kind == ActionKind.TYPE
        assert a.args["text"] == "hello"

    def test_key(self) -> None:
        a = parse_action(
            {"type": "tool_use", "name": "computer", "input": {"action": "key", "key": "Enter"}}
        )
        assert a.kind == ActionKind.KEY
        assert a.args["key"] == "Enter"

    def test_scroll(self) -> None:
        a = parse_action(
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "scroll", "dx": 0, "dy": 600},
            }
        )
        assert a.kind == ActionKind.SCROLL
        assert a.args == {"dx": 0, "dy": 600}

    def test_navigate(self) -> None:
        a = parse_action(
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "navigate", "url": "https://example.com"},
            }
        )
        assert a.kind == ActionKind.NAVIGATE
        assert a.args["url"] == "https://example.com"

    def test_screenshot(self) -> None:
        a = parse_action(
            {"type": "tool_use", "name": "computer", "input": {"action": "screenshot"}}
        )
        assert a.kind == ActionKind.SCREENSHOT

    def test_done_with_final_text(self) -> None:
        a = parse_action(
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "done", "final_text": "Price is $999"},
            }
        )
        assert a.kind == ActionKind.DONE
        assert a.args["final_text"] == "Price is $999"

    def test_unknown_action_is_noop(self) -> None:
        a = parse_action(
            {"type": "tool_use", "name": "computer", "input": {"action": "warble"}}
        )
        assert a.kind == ActionKind.NOOP

    def test_wrong_tool_name_is_noop(self) -> None:
        a = parse_action(
            {"type": "tool_use", "name": "search", "input": {"action": "click"}}
        )
        assert a.kind == ActionKind.NOOP

    def test_finds_block_in_content_list(self) -> None:
        msg = {
            "content": [
                {"type": "text", "text": "thinking..."},
                {
                    "type": "tool_use",
                    "name": "computer",
                    "input": {"action": "click", "coordinate": [10, 20]},
                },
            ]
        }
        a = parse_action(msg)
        assert a.kind == ActionKind.CLICK


# ===========================================================================
# parse_action — plain-text fallback
# ===========================================================================


class TestParseActionPlainText:
    def test_click(self) -> None:
        a = parse_action("ACTION: click 100,200")
        assert a.kind == ActionKind.CLICK
        assert a.args == {"x": 100, "y": 200}

    def test_click_space_separated(self) -> None:
        a = parse_action("ACTION: click 100 200")
        assert a.args == {"x": 100, "y": 200}

    def test_type_with_quotes(self) -> None:
        a = parse_action('ACTION: type "hello world"')
        assert a.kind == ActionKind.TYPE
        assert a.args["text"] == "hello world"

    def test_type_unquoted(self) -> None:
        a = parse_action("ACTION: type hello")
        assert a.kind == ActionKind.TYPE
        assert a.args["text"] == "hello"

    def test_key(self) -> None:
        a = parse_action("ACTION: key Enter")
        assert a.kind == ActionKind.KEY
        assert a.args["key"] == "Enter"

    def test_scroll_two_args(self) -> None:
        a = parse_action("ACTION: scroll 0 600")
        assert a.kind == ActionKind.SCROLL
        assert a.args == {"dx": 0, "dy": 600}

    def test_scroll_single_arg_is_vertical(self) -> None:
        a = parse_action("ACTION: scroll 400")
        assert a.args == {"dx": 0, "dy": 400}

    def test_navigate(self) -> None:
        a = parse_action("ACTION: navigate https://x.com")
        assert a.kind == ActionKind.NAVIGATE
        assert a.args["url"] == "https://x.com"

    def test_done_with_text(self) -> None:
        a = parse_action("ACTION: done The price is $99.")
        assert a.kind == ActionKind.DONE
        assert "The price is $99" in a.args["final_text"]

    def test_picks_last_action_when_multiple(self) -> None:
        a = parse_action("ACTION: click 10,20\nACTION: type hello")
        assert a.kind == ActionKind.TYPE

    def test_keeps_rationale(self) -> None:
        a = parse_action(
            "I'll search by clicking the button first.\nACTION: click 100,200"
        )
        assert "search" in a.rationale

    def test_no_action_line_is_noop(self) -> None:
        a = parse_action("just thinking out loud, no action")
        assert a.kind == ActionKind.NOOP

    def test_empty_string_is_noop(self) -> None:
        a = parse_action("")
        assert a.kind == ActionKind.NOOP

    def test_unknown_command_is_noop(self) -> None:
        a = parse_action("ACTION: warble")
        assert a.kind == ActionKind.NOOP

    def test_text_in_response_dict(self) -> None:
        a = parse_action({"text": "ACTION: click 10,20"})
        assert a.kind == ActionKind.CLICK


# ===========================================================================
# MockBrowserSession (≥10 tests)
# ===========================================================================


class TestMockBrowserSession:
    def test_screenshot_returns_canned(self) -> None:
        b = MockBrowserSession(screenshots=["aaa", "bbb"])
        assert b.screenshot() == "aaa"
        assert b.screenshot() == "bbb"

    def test_screenshot_repeats_last_when_exhausted(self) -> None:
        b = MockBrowserSession(screenshots=["x"])
        assert b.screenshot() == "x"
        assert b.screenshot() == "x"  # doesn't crash

    def test_default_screenshot(self) -> None:
        b = MockBrowserSession()
        # 1×1 PNG base64
        assert isinstance(b.screenshot(), str)

    def test_click_records_call(self) -> None:
        b = MockBrowserSession()
        b.click(10, 20)
        assert ("click", {"x": 10, "y": 20}) in b.calls

    def test_type_records_call(self) -> None:
        b = MockBrowserSession()
        b.type_text("hi")
        assert ("type", {"text": "hi"}) in b.calls

    def test_key_records_call(self) -> None:
        b = MockBrowserSession()
        b.key("Tab")
        assert ("key", {"key": "Tab"}) in b.calls

    def test_scroll_records_call(self) -> None:
        b = MockBrowserSession()
        b.scroll(0, 100)
        assert ("scroll", {"dx": 0, "dy": 100}) in b.calls

    def test_navigate_records_call_and_url(self) -> None:
        b = MockBrowserSession()
        b.navigate("https://example.com")
        assert b.url == "https://example.com"
        assert ("navigate", {"url": "https://example.com"}) in b.calls

    def test_close_records_call(self) -> None:
        b = MockBrowserSession()
        b.close()
        assert ("close", {}) in b.calls

    def test_viewport_size_default(self) -> None:
        b = MockBrowserSession()
        assert b.viewport_size == (1280, 720)

    def test_viewport_size_custom(self) -> None:
        b = MockBrowserSession(viewport_size=(800, 600))
        assert b.viewport_size == (800, 600)


# ===========================================================================
# ComputerUseAgent.run (≥10 tests)
# ===========================================================================


class TestComputerUseAgentRun:
    def test_done_on_first_iteration(self) -> None:
        llm = ScriptedLLM(replies=["ACTION: done The price is $999"])
        browser = MockBrowserSession()
        agent = ComputerUseAgent(
            llm=llm, browser=browser, goal="find iPhone price", max_iterations=5
        )
        result = agent.run()
        assert isinstance(result, ComputerUseResult)
        assert result.status == "done"
        assert result.iterations == 1
        assert "999" in result.final_text

    def test_multi_step_then_done(self) -> None:
        llm = ScriptedLLM(
            replies=[
                "ACTION: click 100,200",
                "ACTION: type apple",
                "ACTION: key Enter",
                "ACTION: done found it",
            ]
        )
        browser = MockBrowserSession()
        agent = ComputerUseAgent(
            llm=llm, browser=browser, goal="search", max_iterations=10
        )
        result = agent.run()
        assert result.status == "done"
        assert result.iterations == 4
        # Each action should have been invoked
        names = [c[0] for c in browser.calls]
        assert "click" in names
        assert "type" in names
        assert "key" in names

    def test_max_iterations_terminates(self) -> None:
        llm = ScriptedLLM(replies=["ACTION: click 1,1"] * 10)
        browser = MockBrowserSession()
        agent = ComputerUseAgent(
            llm=llm, browser=browser, goal="loop", max_iterations=3
        )
        result = agent.run()
        assert result.status == "max_iterations"
        assert result.iterations == 3

    def test_failing_llm_returns_error(self) -> None:
        agent = ComputerUseAgent(
            llm=FailingLLM(),
            browser=MockBrowserSession(),
            goal="x",
            max_iterations=2,
        )
        result = agent.run()
        assert result.status == "error"
        assert "llm call failed" in (result.error or "")

    def test_action_history_records_screenshots(self) -> None:
        llm = ScriptedLLM(replies=["ACTION: done ok"])
        agent = ComputerUseAgent(
            llm=llm, browser=MockBrowserSession(), goal="x", max_iterations=2
        )
        result = agent.run()
        assert len(result.action_history) == 1
        assert result.action_history[0].screenshot_b64

    def test_invalid_max_iterations_raises(self) -> None:
        try:
            ComputerUseAgent(
                llm=ScriptedLLM(),
                browser=MockBrowserSession(),
                goal="x",
                max_iterations=0,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")

    def test_unknown_emit_mode_raises(self) -> None:
        try:
            ComputerUseAgent(
                llm=ScriptedLLM(),
                browser=MockBrowserSession(),
                goal="x",
                action_emit_mode="bogus",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")

    def test_llm_sees_screenshot_in_message(self) -> None:
        llm = ScriptedLLM(replies=["ACTION: done"])
        browser = MockBrowserSession(screenshots=["IMG_BASE64"])
        agent = ComputerUseAgent(llm=llm, browser=browser, goal="g")
        agent.run()
        # Look at the last user message — should contain image content
        first_call_msgs = llm.received[0]
        # System + initial user + screenshot user
        assert len(first_call_msgs) >= 3
        screenshot_msg = first_call_msgs[-1]
        assert screenshot_msg["role"] == "user"
        # Content should be a list with image + text blocks
        content = screenshot_msg["content"]
        assert isinstance(content, list)
        assert any(b.get("type") == "image" for b in content)
        assert any("IMG_BASE64" in b.get("source", {}).get("data", "") for b in content if isinstance(b, dict))

    def test_action_failure_surfaces_to_model(self) -> None:
        # Browser whose click raises
        class BadBrowser(MockBrowserSession):
            def click(self, x: int, y: int) -> None:  # type: ignore[override]
                raise RuntimeError("boom")

        llm = ScriptedLLM(
            replies=[
                "ACTION: click 10,10",
                "ACTION: done recovered",
            ]
        )
        browser = BadBrowser()
        agent = ComputerUseAgent(
            llm=llm, browser=browser, goal="x", max_iterations=5
        )
        result = agent.run()
        assert result.status == "done"
        # First action should have an error recorded
        assert result.action_history[0].error is not None
        assert "boom" in result.action_history[0].error

    def test_navigate_action_runs_browser(self) -> None:
        llm = ScriptedLLM(
            replies=[
                "ACTION: navigate https://apple.com",
                "ACTION: done went there",
            ]
        )
        browser = MockBrowserSession()
        agent = ComputerUseAgent(
            llm=llm, browser=browser, goal="nav", max_iterations=3
        )
        agent.run()
        assert browser.url == "https://apple.com"

    def test_noop_action_just_takes_screenshot(self) -> None:
        # If parser returns NOOP (e.g. response with no ACTION line), the
        # agent should keep going without crashing
        llm = ScriptedLLM(
            replies=[
                "I'm thinking but no action yet",  # noop
                "ACTION: done figured it out",
            ]
        )
        agent = ComputerUseAgent(
            llm=llm, browser=MockBrowserSession(), goal="x", max_iterations=5
        )
        result = agent.run()
        assert result.status == "done"
        assert result.iterations == 2


# ===========================================================================
# Public-import surface
# ===========================================================================


class TestPublicSurface:
    def test_top_level_imports(self) -> None:
        from shipit_agent import (
            ActionKind,
            BrowserSession,
            ComputerAction,
            ComputerUseAgent,
            ComputerUseResult,
            MockBrowserSession,
            parse_action,
        )

        assert ComputerUseAgent is not None
        assert MockBrowserSession is not None
        assert callable(parse_action)
        assert ActionKind.CLICK.value == "click"
        assert ComputerAction is not None
        assert ComputerUseResult is not None
        assert BrowserSession is not None

    def test_subpackage_imports(self) -> None:
        import shipit_agent.computer_use

        assert hasattr(shipit_agent.computer_use, "ComputerUseAgent")
        assert hasattr(shipit_agent.computer_use, "PlaywrightBrowserSession")

    def test_playwright_session_lazy_import(self) -> None:
        # Importing the class should NOT require Playwright. Only .launch() does.
        from shipit_agent.computer_use import PlaywrightBrowserSession

        assert PlaywrightBrowserSession is not None

    def test_action_record_has_default_timestamp(self) -> None:
        from shipit_agent import ActionRecord, ComputerAction, ActionKind

        rec = ActionRecord(
            action=ComputerAction(kind=ActionKind.NOOP),
            screenshot_b64="x",
        )
        assert rec.timestamp > 0
