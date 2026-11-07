"""A wrapped tool_search still counts: deferral must not add a second one.

ShipIt Cloud wraps the built-in tool_search (to drop its long prompt), so
an isinstance check missed it and every run carried both tool_search and
search_tools: about 900 tokens of duplicate prefix on every call.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.tool_search import ToolSearchTool


class _Wrapped:
    """Like Cloud's CompactTool: delegates everything it does not define."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = tool.name

    def schema(self) -> dict[str, Any]:
        return self._tool.schema()

    def run(self, context: Any, **kwargs: Any) -> Any:
        return self._tool.run(context, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(object.__getattribute__(self, "_tool"), item)


class _Records:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.offered: list[str] = []

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        self.offered = [t["function"]["name"] for t in tools or []]
        return LLMResponse(content="done")


def _many_tools() -> list[Any]:
    def make(index: int) -> Any:
        def tool(text: str = "") -> str:
            """A connector action."""
            return text

        return FunctionTool.from_callable(tool, name=f"connector_{index}")

    return [make(i) for i in range(40)]


def test_a_wrapped_tool_search_is_the_only_search_tool() -> None:
    llm = _Records()
    tools = [_Wrapped(ToolSearchTool()), *_many_tools()]
    Agent(llm=llm, tools=tools, deferred_tools=True).run("go")
    searches = [name for name in llm.offered if "search" in name]
    assert searches == ["tool_search"]


def test_without_one_deferral_still_adds_its_own() -> None:
    llm = _Records()
    Agent(llm=llm, tools=_many_tools(), deferred_tools=True).run("go")
    assert [name for name in llm.offered if "search" in name] == ["search_tools"]
