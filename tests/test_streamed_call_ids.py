"""A streamed tool call keeps one id from its first argument fragment to the finished call.

OpenAI-compatible providers send a call's id with its first delta, but not all
of them do: some send it late or never. The id the stream reports for a
fragment must be the id of the call the response returns, or a renderer shows
two calls where there was one.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from shipit_agent.llms.litellm_streaming import _stream_completion
from shipit_agent.llms.openai_streaming import OpenAIStreamingMixin


def _ns(**kwargs: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


def _chunk(*, index: int = 0, call_id: str | None = None, name: str | None = None, args: str | None = None) -> Any:
    fragment = _ns(index=index, id=call_id, function=_ns(name=name, arguments=args))
    delta = _ns(content=None, reasoning_content=None, tool_calls=[fragment])
    return _ns(choices=[_ns(delta=delta, finish_reason=None)], usage=None)


# (description, chunks): the id arrives first, late, or never; two calls, one without ids.
SHAPES = {
    "id first": [_chunk(call_id="call_real", name="echo", args=""), _chunk(args='{"te'), _chunk(args='xt": "hi"}')],
    "id late": [_chunk(name="echo", args='{"te'), _chunk(call_id="call_real", args='xt": "hi"}')],
    "no id": [_chunk(name="echo", args='{"te'), _chunk(args='xt": "hi"}')],
    "two calls, no ids": [
        _chunk(index=0, name="echo", args='{"text": "a"}'),
        _chunk(index=1, name="echo", args='{"text": "b"}'),
    ],
}


def _openai(chunks: list[Any], seen: list[tuple[str, str, str]]) -> Any:
    client = _ns(chat=_ns(completions=_ns(create=lambda **_: iter(chunks))))
    adapter = OpenAIStreamingMixin()
    adapter.model = "gpt-x"
    return adapter._complete_streaming(client, {}, None, lambda *call: seen.append(call))


def _litellm(chunks: list[Any], seen: list[tuple[str, str, str]]) -> Any:
    return _stream_completion(
        completion_fn=lambda **_: iter(chunks), model="m", payload_messages=[], tools=None,
        extra_kwargs={}, text_delta_callback=None, tool_input_callback=lambda *call: seen.append(call),
    )


@pytest.mark.parametrize("adapter", [_openai, _litellm], ids=["openai", "litellm"])
@pytest.mark.parametrize("shape", list(SHAPES))
def test_every_fragment_carries_the_id_the_call_ends_with(adapter: Any, shape: str) -> None:
    seen: list[tuple[str, str, str]] = []
    response = adapter(SHAPES[shape], seen)
    final_ids = [call.id for call in response.tool_calls]
    assert all(final_ids) and len(set(final_ids)) == len(final_ids)
    streamed = [call_id for call_id, _, _ in seen]
    assert set(streamed) == set(final_ids)
    # Fragments of one call share one id, in the order the calls were written.
    assert list(dict.fromkeys(streamed)) == final_ids
    if shape == "id first":
        assert final_ids == ["call_real"]


@pytest.mark.parametrize("adapter", [_openai, _litellm], ids=["openai", "litellm"])
def test_without_a_tool_input_callback_the_providers_late_id_is_kept(adapter: Any) -> None:
    chunks = SHAPES["id late"]
    if adapter is _openai:
        client = _ns(chat=_ns(completions=_ns(create=lambda **_: iter(chunks))))
        mixin = OpenAIStreamingMixin()
        mixin.model = "gpt-x"
        response = mixin._complete_streaming(client, {}, lambda _text: None, None)
    else:
        response = _stream_completion(
            completion_fn=lambda **_: iter(chunks), model="m", payload_messages=[], tools=None,
            extra_kwargs={}, text_delta_callback=lambda _text: None,
        )
    assert [call.id for call in response.tool_calls] == ["call_real"]
