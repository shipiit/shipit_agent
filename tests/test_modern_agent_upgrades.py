"""Tests for the modern-agent upgrades: MCP resources/prompts, streamable
HTTP transport, call correlation ids, result.summary(), durable scheduler,
background subagents, and context compaction."""

from __future__ import annotations

import time
from typing import Any

from shipit_agent import Agent, FunctionTool, SQLiteJobStore
from shipit_agent.llms.base import LLMResponse, ToolCall
from shipit_agent.mcp import (
    MCPError,
    MCPStreamableHTTPTransport,
    RemoteMCPServer,
)
from shipit_agent.schedule import AgentScheduler
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.sub_agent import SubAgentTool


class ScriptedTransport:
    """In-memory MCP transport with canned responses per method."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def request(self, method: str, params: dict | None = None) -> dict:
        self.calls.append(method)
        result = self.responses.get(method)
        if isinstance(result, Exception):
            raise result
        return result or {}

    def close(self) -> None:
        pass


class TestMCPResourcesAndPrompts:
    def _server(self, extra: dict[str, Any]) -> RemoteMCPServer:
        return RemoteMCPServer(
            name="srv",
            transport=ScriptedTransport({"initialize": {}, **extra}),
        )

    def test_list_and_read_resources(self) -> None:
        server = self._server(
            {
                "resources/list": {
                    "resources": [
                        {"uri": "file:///readme", "name": "README",
                         "mimeType": "text/plain"}
                    ]
                },
                "resources/read": {
                    "contents": [{"uri": "file:///readme", "text": "hello world"}]
                },
            }
        )
        resources = server.list_resources()
        assert resources[0].uri == "file:///readme"
        assert resources[0].name == "README"
        assert server.read_resource("file:///readme") == "hello world"

    def test_unsupported_resources_returns_empty(self) -> None:
        server = self._server({"resources/list": MCPError("method not found")})
        assert server.list_resources() == []

    def test_prompts_list_and_get(self) -> None:
        server = self._server(
            {
                "prompts/list": {
                    "prompts": [{"name": "review", "description": "Review code"}]
                },
                "prompts/get": {
                    "messages": [
                        {"role": "user", "content": {"type": "text", "text": "Review this."}}
                    ]
                },
            }
        )
        prompts = server.list_prompts()
        assert prompts[0].name == "review"
        assert server.get_prompt("review") == "Review this."

    def test_resource_tool_lists_and_reads(self) -> None:
        server = self._server(
            {
                "resources/list": {
                    "resources": [{"uri": "db://users", "name": "users table"}]
                },
                "resources/read": {"contents": [{"text": "id,name\n1,ada"}]},
            }
        )
        tool = server.resource_tool()
        assert tool.name == "srv_resources"
        ctx = ToolContext(prompt="", system_prompt="", state={})
        listing = tool.run(ctx)
        assert "db://users" in listing.text
        content = tool.run(ctx, uri="db://users")
        assert "ada" in content.text


class TestStreamableHTTPTransport:
    def test_parses_sse_body(self) -> None:
        body = (
            ": ping\n\n"
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        )
        parsed = MCPStreamableHTTPTransport._parse_sse(body)
        assert parsed["result"] == {"tools": []}

    def test_parses_crlf_sse_after_progress_event(self) -> None:
        body = (
            ": ping\r\n\r\n"
            'event: progress\r\ndata: {"jsonrpc":"2.0","method":"progress"}\r\n\r\n'
            "event: message\r\n"
            'data: {"jsonrpc":"2.0","id":2,"result":{"content":[]}}\r\n\r\n'
        )

        parsed = MCPStreamableHTTPTransport._parse_sse(body)

        assert parsed["result"] == {"content": []}

    def test_sse_without_response_raises(self) -> None:
        try:
            MCPStreamableHTTPTransport._parse_sse(": keepalive\n\n")
        except MCPError as e:
            assert "No JSON-RPC response" in str(e)
        else:
            raise AssertionError("expected MCPError")

    def test_bearer_token_header(self) -> None:
        t = MCPStreamableHTTPTransport("https://x/mcp", bearer_token="tok")
        assert t.headers["authorization"] == "Bearer tok"


class ToolOnceLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, messages, tools=None, **_kw) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[ToolCall(name="add", arguments={"a": 1, "b": 2})]
            )
        return LLMResponse(content="3")


def _add(a: int, b: int, **_ignored: Any) -> str:
    return str(a + b)


def _run() :
    agent = Agent(
        llm=ToolOnceLLM(),
        tools=[FunctionTool.from_callable(_add, name="add")],
        auto_use_skills=False,
    )
    return agent.run("1+2?")


class TestCorrelationAndSummary:
    def test_call_id_pairs_events(self) -> None:
        result = _run()
        called = next(e for e in result.events if e.type == "tool_called")
        done = next(e for e in result.events if e.type == "tool_completed")
        assert called.payload["call_id"] == done.payload["call_id"]
        assert called.payload["call_id"]

    def test_summary_shape(self) -> None:
        result = _run()
        s = result.summary()
        assert s["tool_calls"] == 1
        assert s["tool_failures"] == 0
        assert s["iterations"] >= 1
        assert s["duration_seconds"] >= 0
        assert s["tools"]["add"]["calls"] == 1
        assert s["tools"]["add"]["total_ms"] >= 0


class TestDurableScheduler:
    def test_jobs_survive_restart(self, tmp_path) -> None:
        db = str(tmp_path / "jobs.db")

        class A:
            def run(self, prompt):
                return type("R", (), {"metadata": {}})()

        now = {"t": 1000.0}
        clock = lambda: now["t"]  # noqa: E731

        store = SQLiteJobStore(db)
        s1 = AgentScheduler(A(), clock=clock, sleep=lambda _s: None, store=store)
        job = s1.add("ping", every=60, name="j1")
        first_due = job.next_run
        now["t"] += 60
        s1.run_pending()
        assert job.runs == 1
        store.close()

        # "restart": new store + scheduler, re-add the same job
        store2 = SQLiteJobStore(db)
        s2 = AgentScheduler(A(), clock=clock, sleep=lambda _s: None, store=store2)
        restored = s2.add("ping", every=60, name="j1")
        assert restored.runs == 1                 # run count persisted
        assert restored.next_run == first_due + 60  # slot resumed, not reset
        store2.close()

    def test_store_delete(self, tmp_path) -> None:
        store = SQLiteJobStore(str(tmp_path / "jobs.db"))
        from shipit_agent.schedule import ScheduledJob

        store.save(ScheduledJob(name="x", prompt="p", next_run=5.0))
        assert store.load("x") is not None
        store.delete("x")
        assert store.load("x") is None
        assert store.load_all() == []
        store.close()


class TestBackgroundSubAgent:
    def _tool(self, delay: float = 0.0) -> SubAgentTool:
        class SlowLLM:
            def complete(self, **kwargs):
                if delay:
                    time.sleep(delay)
                return LLMResponse(content="subagent result")

        return SubAgentTool(SlowLLM())

    def test_background_then_collect(self) -> None:
        tool = self._tool(delay=0.05)
        ctx = ToolContext(prompt="", system_prompt="", state={})
        started = tool.run(ctx, task="summarize", background=True)
        task_id = started.metadata["task_id"]
        assert "task-" in task_id
        collected = tool.run(ctx, collect=task_id)
        assert collected.text == "subagent result"
        # collected tasks are cleaned up
        again = tool.run(ctx, collect=task_id)
        assert again.metadata["ok"] is False

    def test_sync_mode_unchanged(self) -> None:
        tool = self._tool()
        ctx = ToolContext(prompt="", system_prompt="", state={})
        out = tool.run(ctx, task="summarize")
        assert out.text == "subagent result"
        assert out.metadata["delegated"] is True
        assert out.metadata["ok"] is True

    def test_unknown_collect_id(self) -> None:
        tool = self._tool()
        ctx = ToolContext(prompt="", system_prompt="", state={})
        out = tool.run(ctx, collect="task-99")
        assert out.metadata["ok"] is False


class TestContextCompaction:
    def test_compaction_emits_event_and_keeps_user_content(self) -> None:
        class ChattyLLM:
            def __init__(self):
                self.n = 0

            def complete(self, *, messages, tools=None, **_kw):
                self.n += 1
                if self.n < 4:
                    return LLMResponse(
                        tool_calls=[ToolCall(name="add", arguments={"a": 1, "b": 2})]
                    )
                return LLMResponse(content="done")

        agent = Agent(
            llm=ChattyLLM(),
            tools=[FunctionTool.from_callable(_add, name="add")],
            auto_use_skills=False,
            max_iterations=8,
            context_window_tokens=50,  # tiny window → compaction triggers
        )
        result = agent.run("Please add numbers repeatedly. " * 30)
        compacted = [e for e in result.events if e.type == "context_compacted"]
        assert compacted
        # Compaction replaces N old messages with one summary — never grows.
        assert compacted[0].payload["after"] <= compacted[0].payload["before"]
