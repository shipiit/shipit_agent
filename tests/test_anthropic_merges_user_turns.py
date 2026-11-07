"""Consecutive user turns reach Anthropic as one message.

A task notification is added as a user message right after the tool
results, which Anthropic also carries as a user message. Two user turns
in a row are combined into one, the results first, as the adapter
already combines several tool results.
"""

from __future__ import annotations

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM


def _convert(messages: list[Message]) -> list[dict]:
    return AnthropicChatLLM(model="claude-sonnet-5-5")._convert_messages(messages)


def test_a_notification_after_tool_results_joins_their_message() -> None:
    out = _convert([
        Message(role="user", content="start"),
        Message(role="assistant", content="", metadata={"tool_calls": [{"id": "t1", "name": "bash", "arguments": {}}]}),
        Message(role="tool", content="started", metadata={"tool_call_id": "t1"}),
        Message(role="user", content="<task-notification>done</task-notification>"),
    ])
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[-1]["content"]] == ["tool_result", "text"]
    assert out[-1]["content"][1]["text"].startswith("<task-notification>")


def test_two_plain_user_turns_join_and_alternation_is_kept() -> None:
    out = _convert([Message(role="user", content="a"), Message(role="user", content="b"),
                    Message(role="assistant", content="c")])
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert [b["text"] for b in out[0]["content"]] == ["a", "b"]
