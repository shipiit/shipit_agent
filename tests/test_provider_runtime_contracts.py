from __future__ import annotations

import time

from shipit_agent import Agent, FunctionTool
from shipit_agent.live import Packet, PacketAccumulator, PacketKind, to_packets
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.capabilities import capabilities_for
from shipit_agent.llms.litellm_adapter import _parse_tool_arguments, _serialize_message
from shipit_agent.models import AgentEvent, Message, ToolCall, pair_calls_and_results
from shipit_agent.tools.helpers import build_tools_prompt


def _search(query: str) -> str:
    """Search a test corpus."""
    return f"found {query}"


SEARCH = FunctionTool.from_callable(_search, name="search_cases")


def test_parallel_tool_policy_is_provider_capability() -> None:
    assert capabilities_for("google.gemma-4-31b").supports_parallel_tool_calls is False
    assert capabilities_for("gpt-5").supports_parallel_tool_calls is True
    assert capabilities_for("a-future-provider/model").supports_parallel_tool_calls is True


def test_tool_prompt_matches_the_models_batching_contract() -> None:
    serial = build_tools_prompt([SEARCH], supports_parallel_tool_calls=False)
    parallel = build_tools_prompt([SEARCH], supports_parallel_tool_calls=True)
    assert "exactly ONE tool call per response" in serial
    assert "Call several tools in ONE response" not in serial
    assert "Call several tools in ONE response" in parallel


def test_v1_metadata_is_normalized_to_v2_pairing_fields() -> None:
    assistant = Message(
        role="assistant",
        metadata={
            "tool_calls": [
                {"id": "provider-call-7", "name": "search_cases", "arguments": {"query": "x"}}
            ]
        },
    )
    result = Message(
        role="tool",
        name="search_cases",
        content="found x",
        metadata={"tool_call_id": "provider-call-7"},
    )
    assert assistant.tool_calls[0].id == "provider-call-7"
    assert result.tool_call_id == "provider-call-7"
    assert pair_calls_and_results([assistant, result]) == (True, [])


def test_wire_serialization_uses_typed_ids_and_provider_reasoning_policy() -> None:
    message = Message(
        role="assistant",
        tool_calls=[ToolCall(name="search_cases", arguments={"query": "x"}, id="p1")],
        metadata={"reasoning_content": "private"},
    )
    ordinary = _serialize_message(message)
    replay = _serialize_message(message, include_reasoning=True)
    assert ordinary["tool_calls"][0]["id"] == "p1"
    assert "reasoning_content" not in ordinary
    assert replay["reasoning_content"] == "private"


def test_malformed_provider_arguments_become_a_recoverable_call() -> None:
    assert _parse_tool_arguments('{"query":') == {"_raw": '{"query":'}
    assert _parse_tool_arguments('["not", "an", "object"]') == {
        "_raw": '["not", "an", "object"]'
    }


def test_live_gemma_bare_prose_argument_is_healed() -> None:
    from shipit_agent.tool_healing import heal_tool_calls

    cleaned, calls = heal_tool_calls(
        "I will search for a tool.\n\n"
        "薬剤call:tool_search{query:current weather in Paris}",
        {"tool_search"},
        schemas={
            "tool_search": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        },
    )
    assert [(call.name, call.arguments) for call in calls] == [
        ("tool_search", {"query": "current weather in Paris"})
    ]
    assert "tool_search{" not in cleaned


def test_live_gemma_call_mapping_is_healed() -> None:
    from shipit_agent.tool_healing import heal_tool_calls

    cleaned, calls = heal_tool_calls(
        'I will search.\n\n<call>{"tool_search":{"query":"weather Paris"}}</call>',
        {"tool_search"},
        schemas={
            "tool_search": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        },
    )
    assert cleaned == "I will search."
    assert [(call.name, call.arguments) for call in calls] == [
        ("tool_search", {"query": "weather Paris"})
    ]


def test_malformed_action_detection_uses_call_structure_not_model_phrases() -> None:
    from shipit_agent.runtime_core import is_malformed_action_attempt

    wreckage = (
        "Starting the requested operation.\n\n"
        'weather_lookup: {"summary": "Look up weather", "x": "'
        + "x" * 400
        + '"}'
    )
    assert is_malformed_action_attempt(
        wreckage, allowed_names={"weather_lookup"}
    ) is True
    assert is_malformed_action_attempt(
        "Here is a complete answer about tools.",
        allowed_names={"weather_lookup"},
    ) is False


def test_whitespace_degenerate_generation_is_recoverable_without_phrase_matching() -> None:
    from shipit_agent.runtime_core import is_malformed_action_attempt

    degenerate = "Starting.\n" + ("  \n" * 120)
    assert is_malformed_action_attempt(
        degenerate, allowed_names={"weather_lookup"}
    ) is True
    assert is_malformed_action_attempt(
        degenerate, allowed_names=()
    ) is False


def test_incomplete_generation_naming_a_registered_tool_is_recoverable() -> None:
    from shipit_agent.runtime_core import is_malformed_action_attempt

    assert is_malformed_action_attempt(
        "I found `weather_lookup` and now I will call",
        allowed_names={"weather_lookup"},
    ) is True
    assert is_malformed_action_attempt(
        "weather_lookup is available.",
        allowed_names={"weather_lookup"},
    ) is False
    assert is_malformed_action_attempt(
        "Used weather_lookup",
        allowed_names={"weather_lookup"},
    ) is False


def test_stream_deadline_is_absolute_not_per_chunk() -> None:
    from shipit_agent.llms.litellm_adapter import _iter_with_deadline

    def slow_chunks():
        for index in range(20):
            time.sleep(0.01)
            yield index

    started = time.monotonic()
    try:
        list(_iter_with_deadline(slow_chunks(), 0.035))
    except TimeoutError:
        pass
    else:
        raise AssertionError("stream should exceed its absolute deadline")
    assert time.monotonic() - started < 0.15


class _NarratingToolLLM:
    model = "google.gemma-4-31b"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, tools=None, text_delta_callback=None, **_kwargs) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            text = "[Executing Tool Calls]"
            if text_delta_callback:
                text_delta_callback(text)
            return LLMResponse(
                content=text,
                tool_calls=[
                    ToolCall(
                        name="search_cases",
                        arguments={"query": "Rosenblum"},
                        id="bedrock-call-1",
                    )
                ],
            )
        if text_delta_callback:
            text_delta_callback("Final answer")
        return LLMResponse(content="Final answer")


def test_tool_step_narration_never_leaks_into_answer_deltas() -> None:
    result = Agent(
        llm=_NarratingToolLLM(),
        tools=[SEARCH],
        max_iterations=2,
        auto_use_skills=False,
    ).run("Search Rosenblum")
    deltas = [event.payload["chunk"] for event in result.events if event.type == "text_delta"]
    assert deltas == ["Final answer"]
    assert result.output == "Final answer"
    assert pair_calls_and_results(result.messages)[0] is True


def test_fallback_call_ids_are_unique_across_chat_turns() -> None:
    class CallsEveryOtherStep:
        model = "provider/model"

        def __init__(self) -> None:
            self.step = 0

        def complete(self, **_kwargs) -> LLMResponse:
            self.step += 1
            if self.step % 2:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(name="search_cases", arguments={"query": "x"})
                    ]
                )
            return LLMResponse(content="done")

    session = Agent(
        llm=CallsEveryOtherStep(), tools=[SEARCH], auto_use_skills=False
    ).chat_session(session_id="unique-call-ids")
    session.send("first")
    session.send("second")

    history = session.history()
    call_ids = [call.id for message in history for call in message.tool_calls]
    assert len(call_ids) == len(set(call_ids)) == 2
    assert pair_calls_and_results(history) == (True, [])


def test_final_packet_replaces_provisional_text_instead_of_duplicating_it() -> None:
    events = [
        AgentEvent(type="text_delta", payload={"chunk": "Final answer"}),
        AgentEvent(type="final_answer", payload={"content": "Final answer"}),
    ]
    accumulator = PacketAccumulator()
    packets = list(to_packets(events))
    for packet in packets:
        accumulator.feed(packet)
    assert packets[-1].text == "Final answer"
    assert accumulator.answer == "Final answer"

    accumulator.feed(Packet(kind=PacketKind.FINAL, text="Canonical"))
    assert accumulator.answer == "Canonical"
