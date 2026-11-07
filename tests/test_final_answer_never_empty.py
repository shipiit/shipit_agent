"""A run never ends with an empty answer, and says why it stopped short.

An empty string tells the caller nothing: not whether the agent ran out of
steps, nor what it did, nor how to carry on. When no answer survives every
recovery, the result explains itself and ``run_summary`` records the reason.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse


def _lookup(query: str = "") -> str:
    """Look something up."""
    return f"result for {query or 'nothing'}"


class _AlwaysCallsTools:
    """Calls the tool on every step, and answers nothing when tools are withheld."""

    def __init__(self, summary: str = "") -> None:
        self.summary = summary
        self.calls = 0

    def complete(self, *, tools: Any = None, **_: Any) -> LLMResponse:
        self.calls += 1
        if not tools:
            return LLMResponse(content=self.summary)
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(name="lookup", arguments={"query": f"q{self.calls}"})],
        )


class _RepeatsThenKeepsCalling:
    """The scripted reproduction: one call six times, then an answer it never reaches.

    After the repeats, the loop withholds tools to force a text answer; this
    model emits the call anyway, the loop ignores it, and nothing is left.
    """

    def __init__(self) -> None:
        call = ToolCall(name="glob_files", arguments={"pattern": "*.txt"})
        self.steps = [LLMResponse(content="", tool_calls=[call]) for _ in range(6)]
        self.steps.append(LLMResponse(content="Done after 6 steps."))

    def complete(self, **_: Any) -> LLMResponse:
        return self.steps.pop(0)


def _agent(llm: Any, **options: Any) -> Agent:
    return Agent(
        llm=llm, tools=[FunctionTool.from_callable(_lookup, name="lookup")], **options
    )


def _summary(result: Any) -> dict[str, Any]:
    return result.metadata["run_summary"]


def test_the_step_limit_with_no_summary_explains_itself() -> None:
    result = _agent(_AlwaysCallsTools(), max_iterations=3).run("go")

    assert result.output.strip()
    assert "step limit (3 steps)" in result.output
    assert "lookup" in result.output
    assert _summary(result)["incomplete_reason"] == "max_iterations"
    assert _summary(result)["completion_status"] == "incomplete"


def test_the_step_limit_keeps_a_real_summary_but_is_still_reported() -> None:
    # With one step, tools are not withheld, so the step ends in a tool call
    # and the loop asks for a summary with no tools.
    llm = _AlwaysCallsTools(summary="Here is what I found so far.")
    result = _agent(llm, max_iterations=1).run("go")

    assert result.output == "Here is what I found so far."
    assert _summary(result)["incomplete_reason"] == "max_iterations"


def test_an_empty_reply_after_ignored_calls_explains_itself(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("x")
    # Read-only, so the loop suppresses the repeats and then forces text.
    glob = get_builtin_tool_map(
        project_root=str(tmp_path), workspace_root=str(tmp_path)
    )["glob_files"]
    result = Agent(llm=_RepeatsThenKeepsCalling(), tools=[glob]).run("go")

    assert result.output.strip()
    assert "no final answer" in result.output
    assert _summary(result)["incomplete_reason"] == "empty_response"


def test_a_finished_run_is_untouched() -> None:
    class _Answers:
        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="All done.")

    result = _agent(_Answers()).run("go")

    assert result.output == "All done."
    assert _summary(result)["incomplete_reason"] is None
    assert _summary(result)["completion_status"] == "finished"


def test_no_tools_ran_is_said_plainly() -> None:
    class _Silent:
        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="")

    result = _agent(_Silent()).run("go")

    assert "No tools ran" in result.output
    assert _summary(result)["incomplete_reason"] == "empty_response"
