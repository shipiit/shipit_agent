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


def test_repeated_generation_is_detected_without_provider_markers() -> None:
    from shipit_agent.action_detection import (
        RepetitionGuard,
        is_malformed_action_attempt,
    )

    guard = RepetitionGuard()
    assert guard.add("I will use the next capability.\n") is False
    stopped = False
    for _ in range(12):
        stopped = guard.add("arbitrary-wrapper: ")
        if stopped:
            break
    assert stopped is True
    assert is_malformed_action_attempt(
        "I will proceed.\n" + ("arbitrary-wrapper:\n" * 20),
        allowed_names={"some_tool"},
    ) is True


def test_explicit_tool_requests_are_resolved_from_the_registry() -> None:
    from shipit_agent.runtime_core import RuntimeCore

    class Tool:
        def __init__(self, name):
            self.name = name

    class Registry:
        def values(self):
            return [Tool(name) for name in (
                "weather_lookup", "orders_db_query", "currency_convert",
                "crm_lookup_customer", "crm_open_tickets",
            )]

    registry = Registry()
    assert RuntimeCore.requested_tool_names(
        "Use the orders tool, then the currency tool.", registry
    ) == {"orders_db_query", "currency_convert"}
    assert RuntimeCore.requested_tool_names(
        "Use the CRM MCP to retrieve open tickets.", registry
    ) == {"crm_open_tickets"}
    assert RuntimeCore.requested_tool_names(
        "Without tools, recall the Berlin weather.", registry
    ) == set()


def test_explicit_tool_request_cannot_finish_with_a_simulated_result() -> None:
    calls: list[str] = []

    class Scripted:
        def __init__(self):
            self.step = 0

        def complete(self, **_kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(content="Pretend console result: 99 degrees")
            if self.step == 2:
                return LLMResponse(tool_calls=[
                    ToolCall(name="weather_lookup", arguments={"city": "Berlin"})
                ])
            return LLMResponse(content="Berlin is 21 degrees")

    def weather(city: str) -> str:
        calls.append(city)
        return "21 degrees"

    result = Agent(
        llm=Scripted(),
        tools=[FunctionTool.from_callable(
            weather, name="weather_lookup", read_only=True
        )],
        auto_use_skills=False,
        max_iterations=4,
    ).run("Use the weather tool for Berlin")
    assert calls == ["Berlin"]
    assert result.output == "Berlin is 21 degrees"
    assert any(
        event.type == "tool_call_healed"
        and event.message == "Retrying an explicitly requested tool"
        for event in result.events
    )


def test_internal_recovery_messages_do_not_shift_human_turn_numbers() -> None:
    from shipit_agent.runtime_core import RuntimeCore

    labelled = RuntimeCore.label_user_turns([
        Message(role="user", content="first"),
        Message(role="user", content="retry", metadata={"internal": True}),
        Message(role="assistant", content="answer"),
        Message(role="user", content="second"),
    ])
    assert labelled[0].content == "[User turn 1]\nfirst"
    assert labelled[1].content == "retry"
    assert labelled[3].content == "second"


def test_repeated_read_call_forces_synthesis_instead_of_looping() -> None:
    executions: list[str] = []

    class Repeater:
        def __init__(self):
            self.step = 0

        def complete(self, *, tools=None, **_kwargs):
            self.step += 1
            if self.step <= 2:
                return LLMResponse(tool_calls=[
                    ToolCall(name="weather_lookup", arguments={"city": "Berlin"})
                ])
            assert tools in (None, [])
            return LLMResponse(content="Berlin is 21 degrees")

    def weather(city: str) -> str:
        executions.append(city)
        return "21 degrees"

    llm = Repeater()
    result = Agent(
        llm=llm,
        tools=[FunctionTool.from_callable(
            weather, name="weather_lookup", read_only=True
        )],
        auto_use_skills=False,
        max_iterations=8,
    ).run("Use the weather tool for Berlin")
    assert executions == ["Berlin"]
    assert llm.step == 3
    assert result.output == "Berlin is 21 degrees"


def test_requested_tool_retry_is_constrained_and_required_when_supported() -> None:
    required_flags: list[bool] = []

    class RequireAware:
        def __init__(self):
            self.step = 0

        def complete(self, *, tools=None, require_tool_call=False, **_kwargs):
            self.step += 1
            required_flags.append(require_tool_call)
            if require_tool_call:
                names = [(schema.get("function") or {}).get("name") for schema in tools]
                assert names == ["currency_convert"]
            if self.step == 1:
                return LLMResponse(content="simulated conversion")
            if self.step == 2:
                assert require_tool_call is True
                return LLMResponse(tool_calls=[
                    ToolCall(name="currency_convert", arguments={"amount": 100})
                ])
            return LLMResponse(content="108 USD")

    result = Agent(
        llm=RequireAware(),
        tools=[FunctionTool.from_callable(
            lambda amount: f"{amount * 1.08} USD",
            name="currency_convert",
            read_only=True,
        )],
        auto_use_skills=False,
        max_iterations=4,
    ).run("Use the currency tool to convert 100 EUR")
    assert required_flags[:2] == [True, True]
    assert result.output == "108 USD"


def test_host_can_require_a_routed_tool_without_prompt_name_matching() -> None:
    calls: list[tuple[list[str], bool]] = []

    class Routed:
        def complete(self, *, tools=None, require_tool_call=False, **_kwargs):
            names = [(schema.get("function") or {}).get("name") for schema in tools]
            calls.append((names, require_tool_call))
            if len(calls) == 1:
                return LLMResponse(tool_calls=[
                    ToolCall(name="remote_search", arguments={"q": "Akira"})
                ])
            return LLMResponse(content="Grounded result")

    result = Agent(
        llm=Routed(),
        tools=[
            FunctionTool.from_callable(
                lambda q: q, name="remote_search", read_only=True
            ),
            FunctionTool.from_callable(
                lambda q: q, name="unrelated_lookup", read_only=True
            ),
        ],
        required_tools=["remote_search"],
        auto_use_skills=False,
        max_iterations=3,
    ).run("Check the named intelligence source for Akira")

    assert calls == [(["remote_search"], True),
                     (["remote_search", "unrelated_lookup"], False)]
    assert result.output == "Grounded result"


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
