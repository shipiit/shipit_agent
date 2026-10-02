"""A guard that says stop must stop an Anthropic stream.

The runtime's repetition and length guards return ``False`` from the text and
tool-input callbacks. The native Anthropic adapter ignored that and then called
``get_final_message()``, which reads — and bills — the rest of the stream
regardless, so no guard could ever cut an Anthropic generation short.
"""

from __future__ import annotations

import sys
import types

from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.models import Message


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


USAGE = _ns(input_tokens=50, output_tokens=7,
            cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _Stream:
    """A fake MessageStream: text chunks or raw events, final message and snapshot."""

    def __init__(self, chunks=(), events=(), tool_block=None):
        self.chunks, self.events, self.tool_block = list(chunks), list(events), tool_block
        self.consumed = 0
        self.final_called = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    @property
    def text_stream(self):
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk

    def __iter__(self):
        for event in self.events:
            self.consumed += 1
            yield event

    def _content(self, upto):
        content = [_ns(type="text", text="".join(self.chunks[:upto]))]
        return content + ([self.tool_block] if self.tool_block is not None else [])

    def get_final_message(self):
        self.final_called = True
        return _ns(content=self._content(len(self.chunks)), usage=USAGE, stop_reason="end_turn")

    @property
    def current_message_snapshot(self):
        return _ns(content=self._content(self.consumed), usage=USAGE, stop_reason=None)


def _install(monkeypatch, stream):
    fake = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **_kwargs):
            raise AssertionError("a streamed call must not fall back to create()")

        def stream(self, **_kwargs):
            return stream

    fake.Anthropic = lambda **_kwargs: _ns(messages=_Messages(), beta=_ns(messages=_Messages()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def _complete(**callbacks):
    llm = AnthropicChatLLM(model="claude-sonnet-4")
    return llm.complete(messages=[Message(role="user", content="hi")], **callbacks)


def _stop_on(n):
    seen = []

    def callback(chunk):
        seen.append(chunk)
        return False if len(seen) >= n else None

    return callback


class TestTextStream:
    def test_a_stop_ends_the_stream_and_keeps_what_was_written(self, monkeypatch):
        stream = _Stream(chunks=["a", "b", "c", "d"])
        _install(monkeypatch, stream)
        response = _complete(text_delta_callback=_stop_on(2))
        assert stream.consumed == 2
        assert stream.final_called is False  # never reads the rest of the stream
        assert stream.closed is True
        assert response.content == "ab"
        assert response.usage["prompt_tokens"] == 50

    def test_an_unstopped_stream_is_unchanged(self, monkeypatch):
        stream = _Stream(chunks=["a", "b", "c"])
        _install(monkeypatch, stream)
        response = _complete(text_delta_callback=lambda _chunk: None)
        assert stream.final_called is True
        assert response.content == "abc"
        assert response.metadata.get("finish_reason") == "end_turn"


def _tool_events(*fragments):
    start = _ns(type="content_block_start", index=1,
                content_block=_ns(type="tool_use", id="t1", name="write_file"))
    deltas = [_ns(type="content_block_delta", index=1,
                  delta=_ns(type="input_json_delta", partial_json=f)) for f in fragments]
    return [start, *deltas]


class TestRawEventStream:
    def test_a_tool_input_stop_never_runs_the_half_written_call(self, monkeypatch):
        partial = _ns(type="tool_use", id="t1", name="write_file", input={"content": "aaa"})
        stream = _Stream(events=_tool_events('{"content": "a', "aa", "aa", "aa"), tool_block=partial)
        _install(monkeypatch, stream)
        response = _complete(text_delta_callback=lambda _c: None,
                             tool_input_callback=lambda _id, _name, _frag: False)
        assert stream.final_called is False
        assert stream.consumed == 2  # the start, then the first fragment
        assert response.tool_calls == []

    def test_a_text_stop_on_the_raw_stream_also_stops(self, monkeypatch):
        text = [_ns(type="content_block_delta", index=0,
                    delta=_ns(type="text_delta", text=t)) for t in ("x", "y", "z")]
        stream = _Stream(events=text)
        _install(monkeypatch, stream)
        _complete(text_delta_callback=_stop_on(1), tool_input_callback=lambda *_a: None)
        assert stream.consumed == 1
        assert stream.final_called is False

    def test_a_completed_tool_call_still_runs_when_nobody_stops(self, monkeypatch):
        done = _ns(type="tool_use", id="t1", name="write_file", input={"content": "ok"})
        stream = _Stream(events=_tool_events('{"content": "ok"}'), tool_block=done)
        _install(monkeypatch, stream)
        response = _complete(text_delta_callback=lambda _c: None,
                             tool_input_callback=lambda *_a: None)
        assert stream.final_called is True
        assert [c.name for c in response.tool_calls] == ["write_file"]
