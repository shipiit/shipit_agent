"""The whole live path: Anthropic's stream, the native adapter, the loop, then the SDK's events."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, StreamEvent, ToolUseBlock, UserMessage, query


def _ns(**kwargs: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


USAGE = _ns(input_tokens=50, output_tokens=7, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _Stream:
    def __init__(self, events: list[Any], content: list[Any], stop_reason: str) -> None:
        self.events, self.content, self.stop_reason = events, content, stop_reason

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def __iter__(self) -> Any:
        return iter(self.events)

    @property
    def text_stream(self) -> Any:
        for event in self.events:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text

    def get_final_message(self) -> Any:
        return _ns(content=self.content, usage=USAGE, stop_reason=self.stop_reason)

    @property
    def current_message_snapshot(self) -> Any:
        return _ns(content=self.content, usage=USAGE, stop_reason=None)


def _text(index: int, *chunks: str) -> list[Any]:
    return [_ns(type="content_block_delta", index=index, delta=_ns(type="text_delta", text=c)) for c in chunks]


def _tool(index: int, call_id: str, name: str, *fragments: str) -> list[Any]:
    start = _ns(type="content_block_start", index=index, content_block=_ns(type="tool_use", id=call_id, name=name))
    deltas = [
        _ns(type="content_block_delta", index=index, delta=_ns(type="input_json_delta", partial_json=f)) for f in fragments
    ]
    return [start, *deltas, _ns(type="content_block_stop", index=index)]


FRAGMENTS = ['{"te', 'xt": "hel', 'lo"}']


@pytest.fixture
def anthropic_streams(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    first = _Stream(
        [*_text(0, "Let me ", "check."), *_tool(1, "toolu_1", "echo", *FRAGMENTS)],
        [_ns(type="text", text="Let me check."), _ns(type="tool_use", id="toolu_1", name="echo", input={"text": "hello"})],
        "tool_use",
    )
    second = _Stream(_text(0, "It said ", "hello."), [_ns(type="text", text="It said hello.")], "end_turn")
    streams, requests = [first, second], []

    class _Messages:
        def stream(self, **kwargs: Any) -> _Stream:
            requests.append(kwargs)
            return streams.pop(0)

        def create(self, **_: Any) -> Any:
            raise AssertionError("a streamed run must not fall back to create()")

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **_: _ns(messages=_Messages(), beta=_ns(messages=_Messages()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return requests


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


def test_text_and_tool_arguments_reach_the_sdk_stream_as_the_provider_sent_them(anthropic_streams: list[dict[str, Any]]) -> None:
    options = AgentOptions(
        llm=AnthropicChatLLM(model="claude-sonnet-5-5", api_key="test"),
        tools=[FunctionTool.from_callable(_echo, name="echo")],
        allowed_tools=["echo"],
        include_partial_messages=True,
        cache_ttl="1h",
    )

    async def run() -> list[Any]:
        return [message async for message in query(prompt="Say hello with the tool.", options=options)]

    messages = asyncio.run(run())
    events = [m.event for m in messages if isinstance(m, StreamEvent)]
    first = events[: [e["type"] for e in events].index("message_stop") + 1]

    text = [e["delta"]["text"] for e in first if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"]
    assert text == ["Let me ", "check."]
    pieces = [e["delta"]["partial_json"] for e in first if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta"]
    assert pieces == FRAGMENTS and json.loads("".join(pieces)) == {"text": "hello"}
    starts = [(e["index"], e["content_block"]["type"]) for e in first if e["type"] == "content_block_start"]
    assert starts == [(0, "text"), (1, "tool_use")]
    assert [e["type"] for e in first].count("content_block_stop") == 2
    assert first[-2]["delta"]["stop_reason"] == "tool_use"

    # The complete call, its result and the final answer all follow.
    call = next(b for m in messages if isinstance(m, AssistantMessage) for b in m.content if isinstance(b, ToolUseBlock))
    assert (call.id, call.name, call.input) == ("toolu_1", "echo", {"text": "hello"})
    result_block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert result_block.content == "echo:hello" and result_block.is_error is False
    final = messages[-1]
    assert isinstance(final, ResultMessage) and final.result == "It said hello." and final.terminal_reason == "completed"
    second_text = [e["delta"]["text"] for e in events[len(first):] if e["type"] == "content_block_delta"]
    assert second_text == ["It said ", "hello."]

    # Both requests asked for the hour-long cache on the system prompt and the tools.
    assert len(anthropic_streams) == 2
    for request in anthropic_streams:
        assert request["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert request["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # The second request carries the tool result, marked as the end of the cached conversation.
    last = anthropic_streams[1]["messages"][-1]["content"][-1]
    assert last["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
