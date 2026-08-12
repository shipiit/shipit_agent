"""Adversarial end-to-end tests for lazy tool and MCP exposure."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool, PermissionEngine, RemoteMCPServer
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class RecordingMCPTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0

    def request(self, method: str, params=None):
        arguments = dict(params or {})
        self.calls.append((method, arguments))
        if method == "initialize":
            return {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "query_production_logs",
                        "description": "Query production application logs.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    }
                ]
            }
        if method == "tools/call":
            return {
                "content": [
                    {"type": "text", "text": "api-1 ERROR request failed"}
                ]
            }
        raise AssertionError(f"unexpected MCP method: {method}")

    def close(self) -> None:
        self.closed += 1


class ScriptedLLM:
    model = "test-model"

    def __init__(self, steps: list[tuple[str, list[tuple[str, dict[str, Any]]]]]):
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    def complete(self, *, messages, tools=None, system_prompt=None, **_kwargs):
        self.requests.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "system_prompt": system_prompt or "",
            }
        )
        content, calls = self.steps.pop(0) if self.steps else ("done", [])
        return LLMResponse(
            content=content,
            tool_calls=[ToolCall(name=name, arguments=args) for name, args in calls],
        )


def _agent(llm: ScriptedLLM, transport: RecordingMCPTransport, **kwargs: Any) -> Agent:
    server = RemoteMCPServer(name="observability", transport=transport)
    return Agent(
        llm=llm,
        mcps=[server],
        auto_use_skills=False,
        max_iterations=5,
        **kwargs,
    )


def _advertised_names(request: dict[str, Any]) -> set[str]:
    return {
        str((schema.get("function") or {}).get("name"))
        for schema in request["tools"]
    }


def test_unrelated_chat_does_not_connect_to_or_execute_mcp() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM([("Hello. How can I help?", [])])

    result = _agent(llm, transport).run("hello")

    methods = [method for method, _ in transport.calls]
    assert methods == []
    assert "tools/call" not in methods
    assert "query_production_logs" not in _advertised_names(llm.requests[0])
    assert {"tool_search", "call_tool"} <= _advertised_names(llm.requests[0])
    assert result.metadata["effective_code_mode"] is False
    assert result.metadata["progressive_tool_context"] is True
    assert result.metadata["deferred_mcp_count"] == 1
    assert result.metadata.get("discovered_mcp_tool_count", 0) == 0
    assert "execute_code" not in _advertised_names(llm.requests[0])


def test_explicitly_requested_unreached_mcp_is_reported() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM([("I could not complete the observability lookup.", [])])

    result = _agent(llm, transport).run("You must use observability for this check")

    assert result.metadata["unmet_requirements"] == ["observability"]
    event = next(e for e in result.events if e.type == "requirements_unmet")
    assert event.payload["requirements"] == ["observability"]


def test_explicitly_named_mcp_tools_are_exposed_directly_for_the_turn() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("query_production_logs", {"query": "service:api level:error"})],
            ),
            ("The API service has a failed request on api-1.", []),
        ]
    )

    result = _agent(llm, transport).run(
        "Use observability to inspect current API errors"
    )

    assert "query_production_logs" in _advertised_names(llm.requests[0])
    assert [method for method, _ in transport.calls] == [
        "initialize",
        "tools/list",
        "tools/call",
    ]
    assert result.output.startswith("The API service")
    assert result.metadata["explicit_mcp_servers"] == ["observability"]
    assert result.metadata["discovered_mcp_tool_count"] == 1
    assert any(
        event.type == "mcp_discovery_completed"
        and event.payload.get("trigger") == "explicit_user_request"
        for event in result.events
    )


def test_strong_local_tool_search_does_not_wake_deferred_mcp() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "read a local project file",
                    "limit": 1,
                    "detail": "schema",
                })],
            ),
            ("Use the local reader.", []),
        ]
    )

    def read_local_file(path: str) -> str:
        return path

    agent = _agent(llm, transport)
    agent.tools.append(
        FunctionTool.from_callable(read_local_file, name="read_local_file")
    )
    result = agent.run("Which tool reads a local project file?")

    assert transport.calls == []
    search_result = next(
        message.content
        for message in result.messages
        if message.role == "tool" and message.name == "tool_search"
    )
    assert "read_local_file" in search_result
    assert not any(
        event.type.startswith("mcp_discovery") for event in result.events
    )


def test_explicit_server_in_original_prompt_overrides_local_search_match() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "retry implementation details",
                    "detail": "schema",
                })],
            ),
            ("Found the observability capability.", []),
        ]
    )

    def read_retry_implementation(path: str) -> str:
        return path

    agent = _agent(llm, transport)
    agent.tools.append(
        FunctionTool.from_callable(
            read_retry_implementation,
            name="read_retry_implementation",
        )
    )
    result = agent.run("Use observability to inspect retry implementation details")

    assert [method for method, _ in transport.calls] == ["initialize", "tools/list"]
    search_result = next(
        message.content
        for message in result.messages
        if message.role == "tool" and message.name == "tool_search"
    )
    assert "query_production_logs" in search_result
    assert "read_retry_implementation" not in search_result


def test_newly_discovered_mcp_defaults_to_bounded_schema_detail() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {"query": "query production application logs"})],
            ),
            ("Found it.", []),
        ]
    )

    result = _agent(llm, transport).run("Use observability to inspect API errors")

    search_result = next(
        item for item in result.tool_results if item.name == "tool_search"
    )
    assert search_result.metadata["detail"] == "schema"
    assert search_result.metadata["detail_upgraded"] is True
    assert len(search_result.metadata["matches"]) <= 3
    assert '"required": ["query"]' in search_result.output


def test_mcp_tool_is_discovered_then_called_with_a_stable_visible_schema_set() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "query production application logs",
                    "limit": 1,
                    "detail": "schema",
                })],
            ),
            (
                "",
                [("call_tool", {
                    "name": "query_production_logs",
                    "arguments": {"query": "service:api level:error"},
                })],
            ),
            ("The API service has a failed request on api-1.", []),
        ]
    )

    result = _agent(llm, transport).run("Find current API errors")

    assert [method for method, _ in transport.calls[:2]] == [
        "initialize",
        "tools/list",
    ]
    remote_calls = [params for method, params in transport.calls if method == "tools/call"]
    assert remote_calls == [
        {
            "name": "query_production_logs",
            "arguments": {"query": "service:api level:error"},
        }
    ]
    assert len(llm.requests) == 3
    assert _advertised_names(llm.requests[0]) == _advertised_names(llm.requests[1])
    search_message = next(
        message for message in result.messages
        if message.role == "tool" and message.name == "tool_search"
    )
    assert '"required": ["query"]' in search_message.content
    final_request_tool_output = next(
        message for message in llm.requests[-1]["messages"]
        if message.role == "tool" and message.name == "call_tool"
    )
    assert "api-1 ERROR request failed" in final_request_tool_output.content
    assert result.output.startswith("The API service")
    assert any(
        event.type == "tool_called"
        and event.payload.get("tool") == "query_production_logs"
        for event in result.events
    )
    assert any(event.type == "mcp_discovery_started" for event in result.events)
    assert any(event.type == "mcp_discovery_completed" for event in result.events)


def test_call_tool_recovers_stringified_argument_object() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "query production application logs",
                    "limit": 1,
                    "detail": "schema",
                })],
            ),
            (
                "",
                [("call_tool", {
                    "name": "query_production_logs",
                    "arguments": '{"query": "service:api"}',
                })],
            ),
            ("Found the API error.", []),
        ]
    )

    result = _agent(llm, transport).run("Find current API errors")

    remote_calls = [params for method, params in transport.calls if method == "tools/call"]
    assert remote_calls == [
        {
            "name": "query_production_logs",
            "arguments": {"query": "service:api"},
        }
    ]
    assert result.output == "Found the API error."


def test_hidden_mcp_tool_keeps_its_own_permission_identity() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "query production application logs",
                    "limit": 1,
                    "detail": "schema",
                })],
            ),
            (
                "",
                [("call_tool", {
                    "name": "query_production_logs",
                    "arguments": {"query": "secret"},
                })],
            ),
            ("The query was denied.", []),
        ]
    )

    result = _agent(
        llm,
        transport,
        permissions=PermissionEngine(deny=["query_production_logs"]),
    ).run("Read the logs")

    assert not any(method == "tools/call" for method, _ in transport.calls)
    assert any(
        event.type == "tool_denied"
        and event.payload.get("tool") == "query_production_logs"
        for event in result.events
    )


def test_stream_reports_hidden_tool_counts_and_real_mcp_activity() -> None:
    transport = RecordingMCPTransport()
    llm = ScriptedLLM(
        [
            (
                "",
                [("tool_search", {
                    "query": "query production application logs",
                    "limit": 1,
                    "detail": "schema",
                })],
            ),
            (
                "",
                [("call_tool", {
                    "name": "query_production_logs",
                    "arguments": {"query": "level:error"},
                })],
            ),
            ("Found one error.", []),
        ]
    )

    events = list(_agent(llm, transport).stream("Find errors"))

    event_types = [event.type for event in events]
    assert event_types[0] == "run_started"
    assert event_types[-1] == "run_completed"
    completed = events[-1]
    assert completed.payload["tool_context"]["hidden"] == 1
    assert completed.payload["tool_context"]["exposed"] >= 2
    assert any(
        event.type == "tool_completed"
        and event.payload.get("tool") == "query_production_logs"
        for event in events
    )
