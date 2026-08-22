from __future__ import annotations

from shipit_agent.context_fit import fit_messages
from shipit_agent.models import Message, ToolCall


def chars(messages) -> int:
    return sum(len(message.text) for message in messages)


def test_short_request_is_untouched() -> None:
    messages = [Message(role="system", content="s"), Message(role="user", content="u")]
    fitted, stats = fit_messages(messages, fits=lambda value: chars(value) <= 10)
    assert fitted == messages
    assert stats == {"dropped_messages": 0, "reduced_messages": 0}


def test_old_turns_drop_as_complete_groups() -> None:
    messages = [Message(role="system", content="system")]
    for index in range(5):
        messages.extend(
            [
                Message(role="user", content=f"user-{index}-" + "u" * 100),
                Message(
                    role="assistant",
                    content="calling",
                    tool_calls=[
                        ToolCall(name="search", arguments={}, id=f"call_{index}")
                    ],
                ),
                Message(
                    role="tool",
                    content="r" * 100,
                    name="search",
                    tool_call_id=f"call_{index}",
                ),
                Message(role="assistant", content=f"answer-{index}"),
            ]
        )
    fitted, stats = fit_messages(messages, fits=lambda value: chars(value) <= 500)
    assert stats["dropped_messages"] > 0
    assert fitted[-4:] == messages[-4:]
    first_non_system = next(message for message in fitted if message.role != "system")
    assert first_non_system.role == "user"


def test_current_tool_result_is_reduced_not_dropped() -> None:
    messages = [
        Message(role="system", content="s"),
        Message(role="user", content="latest request"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(name="search", arguments={}, id="call_x")],
        ),
        Message(role="tool", name="search", tool_call_id="call_x", content="x" * 8000),
    ]
    fitted, stats = fit_messages(messages, fits=lambda value: chars(value) <= 2000)
    tool = next(message for message in fitted if message.role == "tool")
    assert tool.tool_call_id == "call_x"
    assert "omitted to fit" in tool.content
    assert stats["reduced_messages"] > 0


def test_latest_progressive_summary_is_prioritized() -> None:
    old_summary = Message(role="user", content="old", metadata={"compacted": True})
    new_summary = Message(
        role="user", content="new facts", metadata={"compacted": True}
    )
    messages = [
        Message(role="system", content="s"),
        old_summary,
        new_summary,
        Message(role="user", content="latest"),
    ]
    fitted, _ = fit_messages(messages, fits=lambda value: chars(value) <= 15)
    assert new_summary in fitted
    assert old_summary not in fitted
