"""A repeated call is only "no new data" when what the model would see is the same too."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput
from test_tool_output_budget import BIG, run


class _Dump:
    name = "dump"
    description = "Read evidence"
    prompt_instructions = ""

    def __init__(self, views: list[str | None]) -> None:
        self.views = views
        self.calls = 0

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": "dump", "description": "dump",
                                                 "parameters": {"type": "object", "properties": {}}}}

    def run(self, context: Any, **kwargs: Any) -> ToolOutput:
        view = self.views[min(self.calls, len(self.views) - 1)]
        self.calls += 1
        return ToolOutput(text=BIG, model_text=view)


def _tool_messages(tool: _Dump, turns: int) -> list[str]:
    result, _ = run(turns=turns, tools=tool)
    return [str(m.content) for m in result.messages if m.role == "tool"]


def test_a_changed_model_view_of_the_same_raw_output_is_sent() -> None:
    first, second = "first evidence " * 200, "second evidence " * 200
    messages = _tool_messages(_Dump([first, second, second]), turns=3)
    assert "first evidence" in messages[0]
    assert "second evidence" in messages[1]  # same raw body, new view: not a repeat
    assert "No new data" in messages[2]      # same raw body and same view: a repeat


def test_the_same_view_twice_is_still_a_repeat() -> None:
    view = "evidence " * 400
    messages = _tool_messages(_Dump([view]), turns=2)
    assert "evidence" in messages[0] and "No new data" in messages[1]


def test_without_a_model_view_the_raw_output_decides_as_before() -> None:
    messages = _tool_messages(_Dump([None]), turns=2)
    assert "No new data" in messages[1]
