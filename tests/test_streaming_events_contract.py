"""The streamed AgentEvent contract: order, lifecycle, and completeness.

Pins what a caller consuming `agent.stream()` can rely on — the same event
sequence the live Gemma/Bedrock-Mantle harness records, but deterministic.
"""

from __future__ import annotations

from shipit_agent import MCPServer, MCPTool
from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool
from shipit_agent.live import PacketKind, to_packets


class StreamingLLM:
    """Streams text char-by-char (via the callback) and scripts tool calls."""

    def __init__(self, script):
        self.script = list(script)

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        text_delta_callback=None,
    ):
        text, calls = self.script.pop(0) if self.script else ("done", [])
        if text_delta_callback is not None and text and not calls:
            for ch in text:
                text_delta_callback(ch)
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
            usage={"total_tokens": 5},
        )


class EchoTool:
    read_only = True

    def __init__(self, name):
        self.name = name
        self.description = f"{name} tool"

    def schema(self):
        return {"type": "function", "function": {"name": self.name,
                "description": self.description, "parameters": {"type": "object",
                "properties": {}}}}

    def run(self, context, **kwargs):
        return ToolOutput(text=f"{self.name} ran")


def _collect(agent, prompt):
    return list(agent.stream(prompt))


class RecordingLLM:
    def __init__(self):
        self.requests = []
        self.turn = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None,
                 text_delta_callback=None):
        self.requests.append(list(messages))
        self.turn += 1
        return LLMResponse(content=f"answer-{self.turn}", usage={"total_tokens": 5})


def test_plain_agent_keeps_one_session_across_streamed_turns():
    llm = RecordingLLM()
    agent = Agent(
        llm=llm, auto_use_skills=False,
        auto_project_memory=False, skill_source=None,
    )
    session_id = agent.session_id
    _collect(agent, "first question")
    _collect(agent, "follow up about that")
    assert agent.session_id == session_id
    request = "\n".join(str(message.content) for message in llm.requests[1])
    assert "[User turn 1]" in request
    assert "first question" in request
    assert "answer-1" in request
    assert "follow up about that" in request
    assert agent._session_runtime_state["compactor"] is not None


def test_stream_failure_is_a_terminal_event_not_a_second_exception():
    class BrokenLLM:
        def complete(self, **kwargs):
            raise ValueError("bad provider response")

    agent = Agent(
        llm=BrokenLLM(), auto_use_skills=False,
        auto_project_memory=False, skill_source=None,
    )
    events = _collect(agent, "hi")
    assert events[-1].type == "run_failed"
    assert events[-1].payload["error_type"] == "ValueError"
    assert list(to_packets(events))[-1].kind is PacketKind.ERROR


def test_tool_events_use_one_canonical_tool_call_id():
    agent = Agent(
        llm=StreamingLLM([("", [("echo", {})]), ("done", [])]),
        tools=[EchoTool("echo")], auto_use_skills=False,
        auto_project_memory=False, skill_source=None,
    )
    events = [e for e in _collect(agent, "go")
              if e.type in {"tool_called", "tool_completed"}]
    assert len({e.payload["tool_call_id"] for e in events}) == 1
    assert all(e.payload["run_id"] for e in events)
    assert [e.payload["sequence"] for e in events] == sorted(
        e.payload["sequence"] for e in events
    )


def test_agent_owns_mcp_lifetime_across_streamed_turns():
    class CountingMCP:
        name = "counting"
        instructions = ""

        def __init__(self):
            self.close_count = 0

        def discover_tools(self):
            return []

        def close(self):
            self.close_count += 1

    mcp = CountingMCP()
    agent = Agent(
        llm=RecordingLLM(), mcps=[mcp], auto_use_skills=False,
        auto_project_memory=False, skill_source=None,
    )
    _collect(agent, "one")
    _collect(agent, "two")
    assert mcp.close_count == 0
    agent.close()
    agent.close()
    assert mcp.close_count == 1


def test_stream_opens_with_run_started_and_closes_with_run_completed():
    agent = Agent(
        llm=StreamingLLM([("hello world", [])]),
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=2,
    )
    events = _collect(agent, "hi")
    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "final_answer" in types


def test_text_deltas_stream_and_reassemble_to_the_answer():
    agent = Agent(
        llm=StreamingLLM([("streamed answer", [])]),
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=2,
    )
    events = _collect(agent, "hi")
    deltas = [e.payload["chunk"] for e in events if e.type == "text_delta"]
    assert "".join(deltas) == "streamed answer"
    final = next(e for e in events if e.type == "final_answer")
    assert final.payload["content"] == "streamed answer"


def test_tool_lifecycle_events_are_ordered():
    agent = Agent(
        llm=StreamingLLM([("", [("echo", {})]), ("done", [])]),
        tools=[EchoTool("echo")],
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=3,
    )
    types = [e.type for e in _collect(agent, "go")]
    # Every stage fires, in order, for the one tool call.
    for stage in ("tool_group_started", "tool_called", "tool_completed",
                  "tool_group_completed"):
        assert stage in types
    assert types.index("tool_group_started") < types.index("tool_called")
    assert types.index("tool_called") < types.index("tool_completed")
    assert types.index("tool_completed") < types.index("tool_group_completed")


def test_mcp_attached_event_fires_for_a_linked_server():
    crm = MCPServer(name="crm").register(
        MCPTool(name="crm_lookup", description="Look up a customer.",
                handler=lambda context, **k: "ok",
                input_schema={"type": "object", "properties": {}}))
    agent = Agent(
        llm=StreamingLLM([("done", [])]),
        mcps=[crm],
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=2,
    )
    events = _collect(agent, "hi")
    mcp = [e for e in events if e.type == "mcp_attached"]
    assert mcp and mcp[0].payload["server"] == "crm"


def test_ask_user_surfaces_an_interactive_request_event():
    from shipit_agent.tools.ask_user.ask_user_tool import AskUserTool

    agent = Agent(
        llm=StreamingLLM([
            ("", [("ask_user", {"question": "Which environment — prod or staging?"})]),
            ("done", []),
        ]),
        tools=[AskUserTool()],
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=3,
    )
    events = _collect(agent, "deploy it")
    asks = [e for e in events if e.type == "interactive_request"]
    assert asks, "ask_user did not surface an interactive_request"
    q = (asks[0].payload.get("payload") or {}).get("question", "")
    assert "environment" in q


def test_deferred_mcp_tool_is_discovered_then_loaded_in_the_stream():
    crm = MCPServer(name="crm").register(
        MCPTool(name="crm_lookup", description="Look up a customer by company.",
                handler=lambda context, **k: '{"tier": "enterprise"}',
                input_schema={"type": "object",
                              "properties": {"company": {"type": "string"}},
                              "required": ["company"]}))
    agent = Agent(
        llm=StreamingLLM([
            ("", [("tool_search", {"query": "look up a customer in the CRM"})]),
            ("", [("crm_lookup", {"company": "ACME"})]),
            ("done", []),
        ]),
        tools=[ToolSearchTool()],
        mcps=[crm],
        deferred_tools=True,
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=4,
    )
    events = _collect(agent, "look up ACME")
    called = [e.payload["tool"] for e in events if e.type == "tool_called"]
    # tool_search discovered it; then the deferred MCP tool ran directly.
    assert called == ["tool_search", "crm_lookup"]
    completed = [e.payload.get("tool") for e in events if e.type == "tool_completed"]
    assert "crm_lookup" in completed


def test_every_streamed_event_carries_the_full_shape():
    agent = Agent(
        llm=StreamingLLM([("", [("echo", {})]), ("done", [])]),
        tools=[EchoTool("echo")],
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=3,
    )
    for event in _collect(agent, "go"):
        assert isinstance(event.type, str) and event.type
        assert hasattr(event, "message")
        assert isinstance(event.payload, dict)
        assert event.timestamp is not None
