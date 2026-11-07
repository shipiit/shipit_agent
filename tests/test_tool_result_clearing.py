"""Old tool results are cleared from the request, not from the history.

Every turn re-sends the whole conversation, so a long task pays again and
again for files it read twenty turns ago. Once the old results in a
request pass a threshold, the oldest are replaced by a one-line note; the
most recent stay whole. The clearing point only moves forward, in
batches, so the request's prefix (and a provider's prompt cache) changes
rarely. The stored history is never touched.
"""

from __future__ import annotations

from shipit_agent.context.tool_result_clearing import ToolResultClearing, clear_old_tool_results
from shipit_agent.core.models import Message, ToolCall


def _tokens(text: str) -> int:
    return len(text) // 4


def _history(results: int, size: int = 4_000) -> list[Message]:
    messages = [Message(role="system", content="sys"), Message(role="user", content="task")]
    for n in range(results):
        call = ToolCall(id=f"c{n}", name="read_file", arguments={"path": f"f{n}.py"})
        messages.append(Message(role="assistant", content="", tool_calls=[call]))
        messages.append(Message(role="tool", name="read_file", tool_call_id=f"c{n}", content=f"{n}:" + "x" * size))
    return messages


def _cleared(messages: list[Message]) -> list[int]:
    return [i for i, m in enumerate(messages) if m.role == "tool" and m.metadata.get("cleared")]


def test_below_the_threshold_nothing_changes() -> None:
    policy = ToolResultClearing(trigger_tokens=10_000, keep=2)
    messages = _history(5)  # 5 x 1,000 tokens
    out, state = clear_old_tool_results(messages, policy, _tokens, state=None)
    assert out == messages and _cleared(out) == []


def test_past_the_threshold_the_oldest_are_cleared_and_the_newest_kept() -> None:
    policy = ToolResultClearing(trigger_tokens=3_000, keep=2)
    messages = _history(8)
    out, _ = clear_old_tool_results(messages, policy, _tokens, state=None)
    tools = [m for m in out if m.role == "tool"]
    assert all(m.metadata.get("cleared") for m in tools[:3])
    assert [m.content for m in tools[-2:]] == [m.content for m in [m for m in messages if m.role == "tool"][-2:]]
    note = tools[0].content
    assert "read_file" in note and "f0.py" in note and "call it again" in note.lower()
    # what stays fits under the trigger, with room before the next batch
    kept = sum(_tokens(m.content) for m in tools if not m.metadata.get("cleared"))
    assert kept <= policy.trigger_tokens


def test_the_stored_history_is_never_changed() -> None:
    messages = _history(8)
    before = [m.content for m in messages]
    clear_old_tool_results(messages, ToolResultClearing(trigger_tokens=3_000, keep=2), _tokens, state=None)
    assert [m.content for m in messages] == before


def test_the_boundary_only_moves_forward_in_batches() -> None:
    policy = ToolResultClearing(trigger_tokens=3_000, keep=2)
    out, state = clear_old_tool_results(_history(8), policy, _tokens, state=None)
    first = _cleared(out)
    # one more result: still under the trigger after the last batch, so the
    # same results stay cleared and the request's prefix is unchanged
    out2, state2 = clear_old_tool_results(_history(9), policy, _tokens, state=state)
    assert _cleared(out2)[: len(first)] == first
    assert out2[: first[-1] + 1] == out[: first[-1] + 1]
    # it never un-clears, even when told the history is shorter
    out3, _ = clear_old_tool_results(_history(9), policy, _tokens, state=state2)
    assert len(_cleared(out3)) >= len(first)


def test_excluded_tools_and_small_results_are_left_alone() -> None:
    policy = ToolResultClearing(trigger_tokens=1_000, keep=1, exclude_tools=("read_file",))
    out, _ = clear_old_tool_results(_history(6), policy, _tokens, state=None)
    assert _cleared(out) == []
    tiny = _history(30, size=20)  # 30 results of ~5 tokens: clearing them saves nothing
    out, _ = clear_old_tool_results(tiny, ToolResultClearing(trigger_tokens=50, keep=1), _tokens, state=None)
    assert all(len(m.content) >= 20 for m in out if m.role == "tool")


def test_true_means_the_defaults() -> None:
    assert ToolResultClearing.from_setting(True) == ToolResultClearing()
    assert ToolResultClearing.from_setting(None) is None and ToolResultClearing.from_setting(False) is None
    custom = ToolResultClearing(trigger_tokens=5)
    assert ToolResultClearing.from_setting(custom) is custom


def test_after_compaction_drops_old_messages_newer_results_are_not_cleared() -> None:
    policy = ToolResultClearing(trigger_tokens=5_000, keep=2)
    _, state = clear_old_tool_results(_history(8), policy, _tokens, state=None)  # clears c0..c5
    # Compaction then replaced the first six exchanges with a summary. The four
    # results left (c6..c9, ~4,000 tokens) are under the trigger: none is cleared.
    full = _history(10)
    compacted = full[:2] + [Message(role="user", content="summary")] + full[2 + 12:]
    out, _ = clear_old_tool_results(compacted, policy, _tokens, state=state)
    assert [m.tool_call_id for m in out if m.role == "tool"] == ["c6", "c7", "c8", "c9"]
    assert _cleared(out) == []
