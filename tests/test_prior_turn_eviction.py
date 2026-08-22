"""A tool payload is paid for on every turn that follows it, not just its own.

Within a turn the runtime already caps outputs and collapses repeats. Across
turns the whole transcript is reloaded and re-sent: a search that returned
fifteen thousand characters in turn one is billed again on every request of
turn two, three and four — long after the model wrote what mattered into its
answer.

What is kept is the part that stays useful and costs almost nothing: the
call and its arguments, which are what stop the model searching for the same
thing twice. What goes is the payload it has already read.
"""

from __future__ import annotations

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import Message, ToolCall
from shipit_agent.runtime_core import evict_prior_tool_outputs
from shipit_agent.stores import InMemorySessionStore

BIG = "x" * 15_000


class TestWhatIsEvicted:
    def test_a_large_payload_is_replaced(self) -> None:
        [out] = evict_prior_tool_outputs([Message(role="tool", name="s", content=BIG)])
        assert len(out.content) < 400
        assert "omitted from the active prompt" in out.content
        assert "rerun only" in out.content

    def test_a_small_payload_is_left_alone(self) -> None:
        """Below the threshold the notice is the larger of the two."""
        [out] = evict_prior_tool_outputs([Message(role="tool", name="s", content="12")])
        assert out.content == "12"

    def test_user_and_assistant_turns_are_untouched(self) -> None:
        messages = [
            Message(role="user", content=BIG),
            Message(role="assistant", content=BIG),
        ]
        assert [m.content for m in evict_prior_tool_outputs(messages)] == [BIG, BIG]

    def test_no_message_is_ever_dropped(self) -> None:
        """A tool result removed while its assistant tool-call message stays
        is a malformed conversation that some providers reject outright."""
        messages = [
            Message(role="assistant", content="calling"),
            Message(role="tool", name="s", content=BIG),
            Message(role="user", content="next"),
        ]
        out = evict_prior_tool_outputs(messages)
        assert [m.role for m in out] == ["assistant", "tool", "user"]

    def test_the_pairing_identifiers_survive(self) -> None:
        messages = [
            Message(
                role="tool",
                name="search_echo",
                content=BIG,
                metadata={"tool_call_id": "call_7"},
            )
        ]
        [out] = evict_prior_tool_outputs(messages)
        assert out.name == "search_echo"
        assert out.tool_call_id == "call_7"
        assert out.metadata["tool_call_id"] == "call_7"

    def test_persisted_result_pointer_survives(self) -> None:
        message = Message(
            role="tool",
            name="open_url",
            content=BIG,
            tool_call_id="call_8",
            metadata={"persisted_output_path": "/tmp/result.txt"},
        )
        [out] = evict_prior_tool_outputs([message])
        assert "call_id=call_8" in out.content
        assert "stored_at=/tmp/result.txt" in out.content


def _echo(query: str) -> str:
    """Search the echo feed."""
    return BIG


class _Recorder:
    def __init__(self, script) -> None:
        self.script = script
        self.calls = 0
        self.context_chars: list[int] = []

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.context_chars.append(
            sum(len((m.get("content") if isinstance(m, dict) else m.content) or "")
                for m in messages)
        )
        self.calls += 1
        return self.script[min(self.calls - 1, len(self.script) - 1)]


class TestAcrossTurns:
    def _agent(self, llm, store, **kw) -> Agent:
        return Agent(
            llm=llm,
            tools=[FunctionTool.from_callable(_echo, name="search_echo")],
            auto_use_skills=False,
            session_store=store,
            session_id="s1",
            max_iterations=4,
            **kw,
        )

    def _two_turns(self, **kw) -> _Recorder:
        store = InMemorySessionStore()
        call = ToolCall(name="search_echo", arguments={"query": "qilin"})
        first = _Recorder([LLMResponse(tool_calls=[call]), LLMResponse(content="a")])
        self._agent(first, store, **kw).run("turn one")
        second = _Recorder([LLMResponse(content="b")])
        self._agent(second, store, **kw).run("turn two")
        return second

    def test_turn_two_does_not_re_send_turn_ones_payload(self) -> None:
        assert self._two_turns().context_chars[0] < len(BIG)

    def test_keeping_it_is_still_possible(self) -> None:
        """The transcript is the caller's to keep if they want it."""
        recorder = self._two_turns(evict_prior_tool_outputs=False)
        assert recorder.context_chars[0] > len(BIG)

    def test_what_was_searched_for_is_still_visible(self) -> None:
        """The arguments are what stop a second identical search."""
        store = InMemorySessionStore()
        call = ToolCall(name="search_echo", arguments={"query": "qilin"})
        first = _Recorder([LLMResponse(tool_calls=[call]), LLMResponse(content="a")])
        self._agent(first, store).run("turn one")

        seen: list[str] = []

        class Capture(_Recorder):
            def complete(self, *, messages, tools=None, **_kw):
                seen.extend(
                    str((m.get("metadata") if isinstance(m, dict) else m.metadata) or "")
                    + ((m.get("content") if isinstance(m, dict) else m.content) or "")
                    for m in messages
                )
                return super().complete(messages=messages, tools=tools, **_kw)

        self._agent(Capture([LLMResponse(content="b")]), store).run("turn two")
        assert any("qilin" in text for text in seen)
