"""``shipit_agent.sdk.query``: a run as the Claude Agent SDK's message stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import (
    AgentOptions,
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

USAGE = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}


class _Scripted:
    model = "claude-sonnet-5-5"

    def __init__(self, *steps: LLMResponse) -> None:
        self.steps = list(steps)

    def complete(self, **_: Any) -> LLMResponse:
        return self.steps.pop(0) if self.steps else LLMResponse(content="done", usage=USAGE)


class _Streams(_Scripted):
    def complete(self, *, text_delta_callback: Any = None, **kwargs: Any) -> LLMResponse:
        for chunk in ("Hel", "lo"):
            if text_delta_callback is not None:
                text_delta_callback(chunk)
        return LLMResponse(content="Hello", usage=USAGE)


def _call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(
        content="Checking.", tool_calls=[ToolCall(name=name, arguments=arguments, id="c1")], usage=USAGE
    )


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


def _broken(text: str = "") -> str:
    """Always fails."""
    raise ValueError("disk full")


TOOLS = [FunctionTool.from_callable(_echo, name="echo"), FunctionTool.from_callable(_broken, name="broken")]


def _collect(prompt: str = "go", **options: Any) -> list[Any]:
    options.setdefault("tools", TOOLS)

    async def run() -> list[Any]:
        return [message async for message in query(prompt=prompt, options=AgentOptions(**options))]

    return asyncio.run(run())


def test_a_run_is_init_then_assistant_and_tool_results_then_a_result() -> None:
    messages = _collect(llm=_Scripted(_call("echo", text="x")), allowed_tools=["echo"])
    kinds = [type(m).__name__ for m in messages]
    assert kinds == ["SystemMessage", "AssistantMessage", "UserMessage", "AssistantMessage", "ResultMessage"]
    init, first, results, final, result = messages
    assert isinstance(init, SystemMessage) and init.subtype == "init"
    assert init.data["model"] == "claude-sonnet-5-5" and "echo" in init.data["tools"]
    assert isinstance(first, AssistantMessage)
    assert first.content == [TextBlock("Checking."), ToolUseBlock("c1", "echo", {"text": "x"})]
    assert isinstance(results, UserMessage)
    assert results.content == [ToolResultBlock("c1", "echo:x", False)]
    assert isinstance(final, AssistantMessage) and final.content == [TextBlock("done")]
    assert isinstance(result, ResultMessage)
    assert (result.subtype, result.is_error, result.num_turns, result.result) == ("success", False, 2, "done")
    assert result.session_id and result.session_id == init.data["session_id"]
    assert result.total_cost_usd and result.usage["total_tokens"] == 2200


def test_a_failed_tool_is_an_error_result_block() -> None:
    messages = _collect(llm=_Scripted(_call("broken")), allowed_tools=["broken"])
    block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert block.is_error is True and "disk full" in str(block.content)


def test_a_denied_call_is_an_error_block_and_listed_on_the_result() -> None:
    messages = _collect(llm=_Scripted(_call("echo", text="x")), disallowed_tools=["echo(*)"],
                        agent_options={"permissions": {"deny": ["echo"]}})
    block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert block.is_error is True
    result = messages[-1]
    assert result.permission_denials == [{"tool_name": "echo", "tool_use_id": "c1", "tool_input": {"text": "x"}}]


def test_the_turn_limit_ends_the_run_with_its_own_subtype() -> None:
    steps = [_call("echo", text=str(i)) for i in range(5)]
    result = _collect(llm=_Scripted(*steps), max_turns=2)[-1]
    assert result.subtype == "error_max_turns" and result.is_error


def _stream_events(messages: list[Any]) -> list[dict[str, Any]]:
    return [m.event for m in messages if isinstance(m, StreamEvent)]


def test_partial_messages_stream_only_when_asked() -> None:
    with_partial = _collect(llm=_Streams(), include_partial_messages=True)
    deltas = [e["delta"]["text"] for e in _stream_events(with_partial) if e["type"] == "content_block_delta"]
    assert deltas == ["Hel", "lo"]
    assert not any(isinstance(m, StreamEvent) for m in _collect(llm=_Streams()))


def test_a_streamed_response_is_framed_like_the_api_stream() -> None:
    messages = _collect(llm=_Streams(), include_partial_messages=True)
    events = _stream_events(messages)
    assert [e["type"] for e in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert events[0]["message"]["model"] == "claude-sonnet-5-5"
    whole = next(m for m in messages if isinstance(m, AssistantMessage))
    assert whole.message_id == events[0]["message"]["id"]
    assert events[1] == {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    assert events[4] == {"type": "content_block_stop", "index": 0}
    assert events[5]["usage"]["output_tokens"] == 100
    # The whole block arrives as an AssistantMessage before the block is closed.
    kinds = [type(m).__name__ if not isinstance(m, StreamEvent) else m.event["type"] for m in messages]
    assert kinds.index("AssistantMessage") < kinds.index("content_block_stop")


def test_tool_calls_stream_as_tool_use_blocks_before_the_tool_runs() -> None:
    messages = _collect(
        llm=_Scripted(_call("echo", text="hi")), allowed_tools=["echo"], include_partial_messages=True
    )
    events = _stream_events(messages)
    first_turn = events[: [e["type"] for e in events].index("message_stop") + 1]
    assert [e["type"] for e in first_turn] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    # Text the adapter did not stream still arrives, as one chunk.
    assert first_turn[2]["delta"] == {"type": "text_delta", "text": "Checking."}
    assert first_turn[4] == {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "c1", "name": "echo", "input": {}},
    }
    assert json.loads(first_turn[5]["delta"]["partial_json"]) == {"text": "hi"}
    assert first_turn[5]["delta"]["type"] == "input_json_delta"
    assert first_turn[7]["delta"]["stop_reason"] == "tool_use"
    # The tool's result comes after its block is complete.
    positions = [i for i, m in enumerate(messages) if isinstance(m, UserMessage)]
    stop = next(i for i, m in enumerate(messages) if isinstance(m, StreamEvent) and m.event["type"] == "message_stop")
    assert positions and positions[0] > stop


def test_reasoning_streams_as_a_thinking_block_first() -> None:
    thinks = LLMResponse(content="Four.", reasoning_content="2 + 2", usage=USAGE)
    events = _stream_events(_collect(llm=_Scripted(thinks), include_partial_messages=True))
    assert events[1]["content_block"] == {"type": "thinking", "thinking": ""}
    assert events[2]["delta"] == {"type": "thinking_delta", "thinking": "2 + 2"}
    assert events[4]["content_block"]["type"] == "text" and events[4]["index"] == 1


def test_a_response_with_nothing_in_it_opens_no_blocks() -> None:
    events = _stream_events(_collect(llm=_Scripted(LLMResponse(content="", usage=USAGE)), include_partial_messages=True))
    assert "content_block_start" not in [e["type"] for e in events]


def test_a_run_that_raises_ends_with_an_error_result() -> None:
    class _Down:
        model = "x"

        def complete(self, **_: Any) -> LLMResponse:
            raise PermissionError("bad key")

    messages = _collect(llm=_Down(), agent_options={"retry_policy": _no_retries()})
    result = messages[-1]
    assert isinstance(result, ResultMessage)
    assert result.subtype == "error_during_execution" and result.is_error
    assert "bad key" in result.errors[0]


SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}


def test_output_format_gives_structured_output() -> None:
    llm = _Scripted(LLMResponse(content='{"title": "Dune"}'))
    result = _collect(llm=llm, output_format={"type": "json_schema", "schema": SCHEMA})[-1]
    assert result.structured_output == {"title": "Dune"}
    assert result.subtype == "success"


def test_an_answer_that_never_fits_the_format_is_its_own_error() -> None:
    class _Prose(_Scripted):
        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="Sorry, no JSON today.")

    result = _collect(llm=_Prose(), output_format={"type": "json_schema", "schema": SCHEMA})[-1]
    assert result.subtype == "error_max_structured_output_retries" and result.is_error
    assert result.structured_output is None


def _no_retries() -> Any:
    from shipit_agent.core.policies import RetryPolicy

    return RetryPolicy(llm_retry_base_delay=0, max_llm_retries=0)


def test_a_stream_cut_mid_response_still_ends_with_message_stop() -> None:
    class _Dies(_Scripted):
        def complete(self, *, text_delta_callback: Any = None, **kwargs: Any) -> LLMResponse:
            if text_delta_callback is not None:
                text_delta_callback("Hel")
            raise ValueError("connection lost")

    messages = _collect(llm=_Dies(), include_partial_messages=True)
    kinds = [e["type"] for e in _stream_events(messages)]
    assert kinds[-2:] == ["content_block_stop", "message_stop"]
    assert isinstance(messages[-1], ResultMessage) and messages[-1].is_error
