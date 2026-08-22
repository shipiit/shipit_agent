"""The collapsed chat-history shape: lossless round-trip, paused-call safety."""
from shipit_agent.chat_history import collapse, expand, is_collapsed, to_wire_messages
from shipit_agent.models import Message, TextPart, ToolCall, ToolCallPart


def _turn() -> list[Message]:
    """Well-formed wire history: a tool turn plus a plain reply."""
    return [
        Message(role="user", content="find TODOs"),
        Message(
            role="assistant",
            content="Let me look.",
            tool_calls=[ToolCall(name="grep", arguments={"pattern": "TODO"}, id="c1")],
        ),
        Message(
            role="tool",
            content="auth.py:14  # TODO: rotate keys",
            tool_call_id="c1",
            name="grep",
            metadata={"is_error": False, "truncated": False, "duration_ms": 12.0},
        ),
        Message(role="assistant", content="Found it in auth.py"),
    ]


def test_expand_of_collapse_is_the_original():
    """The property that makes the migration safe to run."""
    original = _turn()
    assert expand(collapse(original)) == original


def test_collapse_produces_one_message_per_tool_turn():
    collapsed = collapse(_turn())
    # user, one collapsed assistant turn, the plain reply → 3 messages, not 4.
    assert len(collapsed) == 3
    turn = collapsed[1]
    assert is_collapsed(turn)
    calls = [p for p in turn.content if isinstance(p, ToolCallPart)]
    assert len(calls) == 1 and calls[0].output.startswith("auth.py:14")


def test_collapse_is_idempotent():
    once = collapse(_turn())
    assert collapse(once) == once


def test_a_paused_call_serialises_no_tool_calls_entry():
    """A tool_calls entry with no matching result is what providers reject."""
    paused = [
        Message(role="assistant", content=[
            TextPart("I'll check.", tool_call_ids=["c9"]),
            ToolCallPart(id="c9", name="search", args={"q": "x"}, output=None),  # paused
        ]),
    ]
    wire = to_wire_messages(paused)
    assert wire == [{"role": "assistant", "content": "I'll check."}]  # no tool_calls
    assert "tool_calls" not in wire[0]


def test_a_completed_call_does_serialise_on_the_wire():
    done = [
        Message(role="assistant", content=[
            TextPart("Checking.", tool_call_ids=["c1"]),
            ToolCallPart(id="c1", name="search", args={"q": "x"}, output="found"),
        ]),
    ]
    wire = to_wire_messages(done)
    assert wire[0]["tool_calls"][0]["id"] == "c1"
    assert wire[1] == {"role": "tool", "tool_call_id": "c1", "content": "found"}


def test_a_completed_empty_result_stays_empty_not_a_fake_failure():
    """Providers distinguish a completed empty result from a missing result."""
    done = [
        Message(role="assistant", content=[
            TextPart("Checking.", tool_call_ids=["c1"]),
            ToolCallPart(id="c1", name="search", args={"q": "x"}, output=""),
        ]),
    ]

    expanded = expand(done)
    wire = to_wire_messages(done)

    assert expanded[1].role == "tool"
    assert expanded[1].content == ""
    assert wire[1] == {"role": "tool", "tool_call_id": "c1", "content": ""}


def test_text_keeps_its_association_with_the_calls_it_precedes():
    """Interleaved reasoning and tool use must survive a reload in order."""
    collapsed = collapse([
        Message(role="assistant", content="I'll check two things.",
                tool_calls=[ToolCall(name="a", id="c1"), ToolCall(name="b", id="c2")]),
        Message(role="tool", content="ok1", tool_call_id="c1", name="a"),
        Message(role="tool", content="ok2", tool_call_id="c2", name="b"),
    ])
    text_part = next(p for p in collapsed[0].content if isinstance(p, TextPart))
    assert text_part.tool_call_ids == ["c1", "c2"]


def test_an_unpaired_result_is_kept_not_dropped():
    """Losing history is worse than an odd-looking row."""
    orphan = [Message(role="tool", content="stray", tool_call_id="x", name="t")]
    assert collapse(orphan) == orphan  # passed through, not discarded
