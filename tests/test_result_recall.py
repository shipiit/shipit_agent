from __future__ import annotations

from shipit_agent.models import Message
from shipit_agent.registry import ToolRegistry
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.recall_result import RecallToolResult
from shipit_agent.tools.recall_result.recall_result_tool import recallable_results


BIG = "0123456789" * 500


def test_only_large_paired_results_are_indexed() -> None:
    messages = [
        Message(role="tool", name="search", content=BIG, tool_call_id="call_1"),
        Message(role="tool", name="small", content="ok", tool_call_id="call_2"),
        Message(role="tool", name="unpaired", content=BIG),
    ]
    results = recallable_results(messages, min_chars=1000)
    assert list(results) == ["call_1"]
    assert results["call_1"].output == BIG


def test_recall_returns_bounded_pages_with_continuation() -> None:
    result = recallable_results(
        [Message(role="tool", name="search", content=BIG, tool_call_id="call_1")],
        min_chars=1000,
    )
    tool = RecallToolResult(result)
    first = tool.run(None, call_id="call_1", offset=0, limit=1000)
    second = tool.run(None, call_id="call_1", offset=1000, limit=1000)
    assert "chars 0:1000" in first.text
    assert "continue with offset=1000" in first.text
    assert "chars 1000:2000" in second.text


def test_unknown_call_id_is_a_recoverable_result() -> None:
    tool = RecallToolResult({})
    output = tool.run(None, call_id="missing")
    assert output.metadata["is_error"] is True
    assert "No recallable result" in output.text


def test_literal_search_retrieves_small_exact_excerpt_from_large_result():
    text = "unrelated evidence\n" * 20000 + "Invoice [A-42]: EUR 720" + "\nother" * 20000
    tool = RecallToolResult(recallable_results([
        Message(role="tool", name="search", content=text, tool_call_id="large")
    ], min_chars=1000))
    output = tool.run(None, call_id="large", query="invoice [a-42]", limit=512)
    assert "Invoice [A-42]: EUR 720" in output.text
    assert len(output.text) < 750
    assert output.metadata["matched"] is True
    assert output.metadata["match_offset"] == text.index("Invoice")
    assert output.text.split("\n", 1)[1] == text[output.metadata["offset"]:output.metadata["next_offset"]]
    absent = tool.run(None, call_id="large", query="not-present")
    assert absent.metadata["matched"] is False


def test_recall_offset_beyond_end_is_clamped():
    tool = RecallToolResult(recallable_results([
        Message(role="tool", content=BIG, tool_call_id="large")
    ], min_chars=1000))
    output = tool.run(None, call_id="large", offset=999999)
    assert output.metadata["offset"] == len(BIG)
    assert output.metadata["next_offset"] is None


def test_runtime_installs_recall_only_when_useful() -> None:
    registry = ToolRegistry()
    name = AgentRuntime.install_result_recall(
        registry,
        [Message(role="tool", name="search", content=BIG, tool_call_id="call_1")],
    )
    assert name == "recall_tool_result"
    assert registry.get(name) is not None

    empty = ToolRegistry()
    assert AgentRuntime.install_result_recall(empty, []) == ""
    assert empty.values() == []
