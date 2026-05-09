"""Tests for ``BrowserAgentTool`` — the adapter that lets the main
``Agent`` use a ``ComputerUseAgent`` as a tool.

≥10 tests covering: tool protocol surface, schema, run with/without
context, error handling, share_browser mode, custom names, and the
parent → sub-agent integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.computer_use import (
    BrowserAgentTool,
    MockBrowserSession,
)


@dataclass
class ScriptedLLM:
    replies: list[str] = field(default_factory=list)
    _i: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
        if self._i >= len(self.replies):
            raise RuntimeError("ScriptedLLM exhausted")
        out = self.replies[self._i]
        self._i += 1
        return out


def _factory(canned_replies: list[str], browsers_seen: list[Any]) -> Any:
    """Build a browser_factory that records every browser it makes."""

    def make() -> MockBrowserSession:
        b = MockBrowserSession()
        browsers_seen.append(b)
        return b

    return make


# ===========================================================================
# Protocol surface
# ===========================================================================


class TestBrowserAgentToolProtocol:
    def test_default_name(self) -> None:
        tool = BrowserAgentTool(llm=ScriptedLLM(), browser_factory=lambda: MockBrowserSession())
        assert tool.name == "browser_use"

    def test_custom_name(self) -> None:
        tool = BrowserAgentTool(
            llm=ScriptedLLM(),
            browser_factory=lambda: MockBrowserSession(),
            name="drive_browser",
        )
        assert tool.name == "drive_browser"

    def test_has_description(self) -> None:
        tool = BrowserAgentTool(llm=ScriptedLLM(), browser_factory=lambda: MockBrowserSession())
        assert "browser" in tool.description.lower()

    def test_schema_requires_goal(self) -> None:
        tool = BrowserAgentTool(llm=ScriptedLLM(), browser_factory=lambda: MockBrowserSession())
        schema = tool.schema()
        assert "goal" in schema["properties"]
        assert schema["required"] == ["goal"]

    def test_schema_goal_is_string(self) -> None:
        tool = BrowserAgentTool(llm=ScriptedLLM(), browser_factory=lambda: MockBrowserSession())
        assert tool.schema()["properties"]["goal"]["type"] == "string"


# ===========================================================================
# Run behaviour
# ===========================================================================


class TestBrowserAgentToolRun:
    def test_no_goal_returns_error_output(self) -> None:
        tool = BrowserAgentTool(llm=ScriptedLLM(), browser_factory=lambda: MockBrowserSession())
        result = tool.run()
        assert "no `goal`" in result.text
        assert result.metadata["error"] == "missing-goal"

    def test_done_first_iteration_returns_text(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done The price is $999"]),
            browser_factory=_factory([], seen),
        )
        result = tool.run(goal="Find the iPhone price")
        assert "999" in result.text
        assert result.metadata["status"] == "done"
        assert result.metadata["iterations"] == 1

    def test_actions_recorded_in_metadata(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=[
                "ACTION: navigate https://x.com",
                "ACTION: done navigated",
            ]),
            browser_factory=_factory([], seen),
        )
        result = tool.run(goal="visit x.com")
        actions = result.metadata["actions"]
        assert len(actions) == 2
        assert actions[0]["kind"] == "navigate"
        assert actions[1]["kind"] == "done"

    def test_max_iterations_reflected_in_metadata(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: click 1,1"] * 5),
            browser_factory=_factory([], seen),
            max_iterations=2,
        )
        result = tool.run(goal="click")
        assert result.metadata["status"] == "max_iterations"
        assert result.metadata["iterations"] == 2

    def test_format_includes_goal(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done ok"]),
            browser_factory=_factory([], seen),
        )
        out = tool.run(goal="find the answer")
        assert "find the answer" in out.text

    def test_format_includes_final_text(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done The answer is 42"]),
            browser_factory=_factory([], seen),
        )
        out = tool.run(goal="figure it out")
        assert "42" in out.text


# ===========================================================================
# Browser lifecycle
# ===========================================================================


class TestBrowserLifecycle:
    def test_default_no_share_creates_new_browser_per_call(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done a", "ACTION: done b"]),
            browser_factory=_factory([], seen),
            share_browser=False,
        )
        tool.run(goal="first")
        tool.run(goal="second")
        assert len(seen) == 2

    def test_share_browser_reuses_same_session(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done a", "ACTION: done b"]),
            browser_factory=_factory([], seen),
            share_browser=True,
        )
        tool.run(goal="first")
        tool.run(goal="second")
        # Only one browser created — reused across runs
        assert len(seen) == 1

    def test_close_releases_shared_browser(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done a"]),
            browser_factory=_factory([], seen),
            share_browser=True,
        )
        tool.run(goal="first")
        # Browser should still be alive
        first = seen[0]
        assert ("close", {}) not in first.calls
        # close() should call .close() on the held browser
        tool.close()
        assert ("close", {}) in first.calls

    def test_no_share_browser_closed_per_call(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done a"]),
            browser_factory=_factory([], seen),
            share_browser=False,
        )
        tool.run(goal="x")
        # Each browser is closed when its run finishes
        assert ("close", {}) in seen[0].calls


# ===========================================================================
# Integration with main Agent
# ===========================================================================


class TestAgentIntegration:
    def test_browser_tool_passes_protocol_check(self) -> None:
        """The tool should be acceptable as a value in Agent.tools."""
        tool = BrowserAgentTool(
            llm=ScriptedLLM(),
            browser_factory=lambda: MockBrowserSession(),
        )
        # All Tool-protocol attributes present
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "schema")
        assert hasattr(tool, "run")
        assert callable(tool.schema)
        assert callable(tool.run)

    def test_can_be_added_to_agent_tools_list(self) -> None:
        from shipit_agent import Agent

        tool = BrowserAgentTool(
            llm=ScriptedLLM(),
            browser_factory=lambda: MockBrowserSession(),
        )
        agent = Agent(llm=ScriptedLLM(), tools=[tool], auto_use_skills=False)
        # Verify the tool is in the effective set
        effective = agent._effective_tools("any")  # noqa: SLF001
        assert any(t.name == "browser_use" for t in effective)


# ===========================================================================
# Public surface
# ===========================================================================


class TestPublicSurface:
    def test_top_level_import(self) -> None:
        from shipit_agent.computer_use import BrowserAgentTool

        assert BrowserAgentTool is not None

    def test_metadata_serializable(self) -> None:
        seen: list[Any] = []
        tool = BrowserAgentTool(
            llm=ScriptedLLM(replies=["ACTION: done ok"]),
            browser_factory=_factory([], seen),
        )
        out = tool.run(goal="x")
        # Metadata should round-trip through JSON
        json.dumps(out.metadata)
