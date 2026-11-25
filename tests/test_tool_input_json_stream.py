"""A tool call's arguments as raw JSON while the model writes them."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, AssistantMessage, StreamEvent, UserMessage, query


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


TOOLS = [FunctionTool.from_callable(_echo, name="echo")]


class _Writes:
    """Streams each call's arguments in pieces, then returns the calls."""

    model = "claude-sonnet-5-5"

    def __init__(self, *calls: tuple[str, str, list[str]], final_ids: list[str] | None = None) -> None:
        self.calls = list(calls)
        self.final_ids = final_ids
        self.turn = 0

    def complete(self, *, tool_input_callback: Any = None, text_delta_callback: Any = None, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn > 1:
            return LLMResponse(content="done")
        made = []
        for index, (call_id, name, pieces) in enumerate(self.calls):
            for piece in pieces:
                if tool_input_callback is not None:
                    tool_input_callback(call_id, name, piece)
            final_id = self.final_ids[index] if self.final_ids else call_id
            made.append(ToolCall(name=name, arguments=json.loads("".join(pieces)), id=final_id))
        return LLMResponse(content="", tool_calls=made)


ONE = ("c1", "echo", ['{"te', 'xt": "h', 'i"}'])


def _json_deltas(events: list[Any]) -> list[dict[str, Any]]:
    return [e.payload for e in events if e.type == "tool_input_json_delta"]


def test_the_loop_emits_raw_fragments_only_when_asked() -> None:
    state, _ = AgentRuntime(llm=_Writes(ONE), prompt="p", tools=TOOLS, stream_tool_input_json=True).run("go")
    deltas = _json_deltas(state.events)
    assert [d["partial_json"] for d in deltas] == ONE[2]
    assert {(d["call_id"], d["tool"]) for d in deltas} == {("c1", "echo")}
    quiet, _ = AgentRuntime(llm=_Writes(ONE), prompt="p", tools=TOOLS).run("go")
    assert _json_deltas(quiet.events) == []


def test_the_agent_setting_reaches_the_loop() -> None:
    result = Agent(llm=_Writes(ONE), tools=TOOLS, stream_tool_input_json=True).run("go")
    assert [d["partial_json"] for d in _json_deltas(result.events)] == ONE[2]
    assert _json_deltas(Agent(llm=_Writes(ONE), tools=TOOLS).run("go").events) == []


def _stream(llm: Any, **options: Any) -> list[Any]:
    async def run() -> list[Any]:
        opts = AgentOptions(llm=llm, tools=TOOLS, allowed_tools=["echo"], include_partial_messages=True, **options)
        return [message async for message in query(prompt="go", options=opts)]

    return asyncio.run(run())


def _first_response(messages: list[Any]) -> list[dict[str, Any]]:
    events = [m.event for m in messages if isinstance(m, StreamEvent)]
    return events[: [e["type"] for e in events].index("message_stop") + 1]


def test_sdk_tool_input_streams_in_pieces_and_is_not_sent_again_whole() -> None:
    messages = _stream(_Writes(ONE))
    events = _first_response(messages)
    assert [e["type"] for e in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert events[1]["content_block"] == {"type": "tool_use", "id": "c1", "name": "echo", "input": {}}
    pieces = [e["delta"]["partial_json"] for e in events if e["type"] == "content_block_delta"]
    assert pieces == ONE[2] and json.loads("".join(pieces)) == {"text": "hi"}
    # The block starts before the response is complete, and the tool runs after it.
    order = [m.event["type"] if isinstance(m, StreamEvent) else type(m).__name__ for m in messages]
    assert order.index("content_block_start") < order.index("AssistantMessage") < order.index("UserMessage")
    assert any(isinstance(m, UserMessage) for m in messages)


def test_two_calls_stream_as_two_blocks_in_order() -> None:
    second = ("c2", "echo", ['{"text":', ' "yo"}'])
    events = _first_response(_stream(_Writes(ONE, second)))
    starts = [e for e in events if e["type"] == "content_block_start"]
    assert [(s["index"], s["content_block"]["id"]) for s in starts] == [(0, "c1"), (1, "c2")]
    by_index: dict[int, str] = {}
    for event in events:
        if event["type"] == "content_block_delta":
            by_index[event["index"]] = by_index.get(event["index"], "") + event["delta"]["partial_json"]
    assert {i: json.loads(text) for i, text in by_index.items()} == {0: {"text": "hi"}, 1: {"text": "yo"}}


def test_a_call_whose_final_id_differs_still_gets_a_whole_block() -> None:
    messages = _stream(_Writes(ONE, final_ids=["final-1"]))
    events = _first_response(messages)
    starts = [e["content_block"]["id"] for e in events if e["type"] == "content_block_start"]
    assert starts == ["c1", "final-1"]
    whole = [e["delta"]["partial_json"] for e in events if e["type"] == "content_block_delta" and e["index"] == 1]
    assert [json.loads(text) for text in whole] == [{"text": "hi"}]
    assert [e["type"] for e in events].count("content_block_stop") == 2
    call = next(m for m in messages if isinstance(m, AssistantMessage)).content[0]
    assert call.id == "final-1"


def test_without_partial_messages_the_sdk_does_not_turn_fragments_on() -> None:
    from shipit_agent.sdk import build_agent

    assert build_agent(AgentOptions(llm=_Writes(ONE), tools=TOOLS)).stream_tool_input_json is False
    assert build_agent(AgentOptions(llm=_Writes(ONE), tools=TOOLS, include_partial_messages=True)).stream_tool_input_json is True


def test_raw_fragments_pass_through_the_live_and_sse_serializers() -> None:
    from shipit_agent.core.packets import sse_event_stream
    from shipit_agent.observability.live import to_packets

    result = Agent(llm=_Writes(ONE), tools=TOOLS, stream_tool_input_json=True).run("go")
    fragments = [e for e in result.events if e.type == "tool_input_json_delta"]
    assert len(fragments) == 3
    packets = list(to_packets(fragments))
    # to_packets always closes with one terminal packet of its own.
    pieces = [packet.data["partial_json"] for packet in packets if not packet.is_terminal]
    assert pieces == ONE[2] and packets[-1].is_terminal
    lines = sse_event_stream(fragments)
    assert len(lines) == 3 and all('"partial_json"' in line for line in lines)
