"""Tests for LangfuseExporter — v2 ingestion + v3 OTLP wire formats."""

from __future__ import annotations

import base64
import json

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.tracing_exporters import LangfuseExporter


def _events():
    return [
        AgentEvent(type="run_started", message="", timestamp=100.0,
                   payload={"prompt": "Close Q2"}),
        AgentEvent(type="tool_called", message="", timestamp=101.0,
                   payload={"tool": "build_document", "call_id": "c1",
                            "arguments": {"kind": "xlsx"}}),
        AgentEvent(type="tool_completed", message="", timestamp=102.5,
                   payload={"tool": "build_document", "call_id": "c1",
                            "output": "Created XLSX", "duration_ms": 1500.0}),
        AgentEvent(type="run_completed", message="", timestamp=103.0,
                   payload={"output": "Workbook ready."}),
    ]


def _run(exporter):
    for e in _events():
        exporter.append_event("trace-1", e, {"agent_name": "finance-analyst"})


class _Capture:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))


class TestV3OTLP:
    def test_otlp_payload_shape(self) -> None:
        cap = _Capture()
        _run(LangfuseExporter(public_key="pk", secret_key="sk",
                              host="https://lf.example.com",
                              api_version="v3", transport=cap))
        assert len(cap.calls) == 1
        url, headers, body = cap.calls[0]
        assert url == "https://lf.example.com/api/public/otel/v1/traces"
        assert headers["authorization"] == "Basic " + base64.b64encode(b"pk:sk").decode()

        spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 2  # root agent span + one tool span
        root, tool = spans
        assert root["name"] == "finance-analyst"
        assert root["parentSpanId"] if False else "parentSpanId" not in root
        assert tool["parentSpanId"] == root["spanId"]
        assert tool["name"] == "build_document"
        # duration from duration_ms: 102.5 - 1.5 = 101.0
        assert int(tool["startTimeUnixNano"]) == int(101.0 * 1e9)
        assert int(tool["endTimeUnixNano"]) == int(102.5 * 1e9)
        # ids: 32-hex trace, 16-hex span, consistent across spans
        assert len(root["traceId"]) == 32 and root["traceId"] == tool["traceId"]
        assert len(tool["spanId"]) == 16

    def test_failed_tool_gets_error_status(self) -> None:
        cap = _Capture()
        exporter = LangfuseExporter(public_key="p", secret_key="s",
                                    api_version="v3", transport=cap)
        exporter.append_event("t", AgentEvent(type="tool_called", message="",
                              timestamp=1.0, payload={"tool": "bash", "call_id": "x"}))
        exporter.append_event("t", AgentEvent(type="tool_failed", message="",
                              timestamp=2.0, payload={"tool": "bash", "call_id": "x",
                                                       "error": "boom"}))
        exporter.append_event("t", AgentEvent(type="run_completed", message="",
                              timestamp=3.0, payload={"output": "done"}))
        spans = cap.calls[0][2]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        tool = spans[1]
        assert tool["status"]["code"] == 2
        assert any(a["value"]["stringValue"] == "boom"
                   for a in tool["attributes"] if a["key"] == "output.value")


class TestV2Ingestion:
    def test_batch_payload_shape(self) -> None:
        cap = _Capture()
        _run(LangfuseExporter(public_key="pk", secret_key="sk",
                              host="https://lf2.example.com",
                              api_version="v2", transport=cap))
        url, _headers, body = cap.calls[0]
        assert url == "https://lf2.example.com/api/public/ingestion"
        batch = body["batch"]
        assert [item["type"] for item in batch] == ["trace-create", "span-create"]
        trace_body = batch[0]["body"]
        assert trace_body["name"] == "finance-analyst"
        assert trace_body["input"] == "Close Q2"
        assert trace_body["output"] == "Workbook ready."
        span_body = batch[1]["body"]
        assert span_body["traceId"] == trace_body["id"]
        assert span_body["name"] == "build_document"
        assert span_body["startTime"].endswith("Z")


class TestBehavior:
    def test_auto_detects_v2_from_health(self, monkeypatch) -> None:
        cap = _Capture()
        exporter = LangfuseExporter(public_key="p", secret_key="s",
                                    api_version="auto", transport=cap)
        monkeypatch.setattr(
            exporter, "_resolve_version", lambda: exporter.__dict__.setdefault(
                "_resolved_version", "v2") or "v2")
        _run(exporter)
        assert cap.calls[0][0].endswith("/api/public/ingestion")

    def test_invalid_api_version_rejected(self) -> None:
        with pytest.raises(ValueError, match="api_version"):
            LangfuseExporter(api_version="v4")

    def test_transport_errors_never_raise(self) -> None:
        def boom(*_a):
            raise RuntimeError("network down")

        exporter = LangfuseExporter(public_key="p", secret_key="s",
                                    api_version="v3", transport=boom)
        _run(exporter)  # must not raise — observability can't break the run

    def test_load_returns_none(self) -> None:
        assert LangfuseExporter(api_version="v3").load("x") is None


class TestEndToEndAgainstFakeServer:
    """Real HTTP + real Agent: the full path an actual deployment takes."""

    @pytest.fixture()
    def fake_langfuse(self):
        import http.server
        import threading

        received = {"otel": [], "ingestion": [], "health_hits": 0}

        def make_handler(version: str):
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/api/public/health":
                        received["health_hits"] += 1
                        body = json.dumps({"version": version,
                                           "status": "OK"}).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                def do_POST(self):
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length))
                    entry = {"path": self.path, "payload": payload,
                             "auth": self.headers.get("Authorization", "")}
                    if "otel" in self.path:
                        received["otel"].append(entry)
                    else:
                        received["ingestion"].append(entry)
                    self.send_response(207)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")

                def log_message(self, *_a):
                    pass

            return Handler

        def start(version: str):
            server = http.server.HTTPServer(("127.0.0.1", 0),
                                            make_handler(version))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            return server, f"http://127.0.0.1:{server.server_port}"

        yield start, received

    def _run_real_agent(self, exporter):
        from shipit_agent import Agent, FunctionTool
        from shipit_agent.llms.base import LLMResponse, ToolCall

        class L:
            def __init__(self):
                self.turn = 0

            def complete(self, *, messages, tools=None, **_kw):
                self.turn += 1
                if self.turn == 1:
                    return LLMResponse(tool_calls=[
                        ToolCall(name="add", arguments={"a": 2, "b": 3})])
                return LLMResponse(content="The sum is 5.")

        def add(a: int, b: int, **_):
            return str(a + b)

        agent = Agent(llm=L(),
                      tools=[FunctionTool.from_callable(add, name="add")],
                      auto_use_skills=False, trace_store=exporter)
        return agent.run("what is 2+3?")

    def test_real_agent_traced_to_v3_server_with_autodetect(self, fake_langfuse) -> None:
        start, received = fake_langfuse
        server, host = start("3.121.0")
        try:
            exporter = LangfuseExporter(public_key="pk", secret_key="sk",
                                        host=host, api_version="auto")
            result = self._run_real_agent(exporter)
            assert result.output == "The sum is 5."
            # auto-detect probed health once and chose OTLP
            assert received["health_hits"] == 1
            assert len(received["otel"]) == 1
            assert received["ingestion"] == []
            entry = received["otel"][0]
            assert entry["auth"].startswith("Basic ")
            spans = entry["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
            names = [s["name"] for s in spans]
            assert "add" in names          # the tool span made it to the server
            tool = next(s for s in spans if s["name"] == "add")
            assert int(tool["endTimeUnixNano"]) >= int(tool["startTimeUnixNano"])
        finally:
            server.shutdown()

    def test_real_agent_traced_to_v2_server_with_autodetect(self, fake_langfuse) -> None:
        start, received = fake_langfuse
        server, host = start("2.93.1")
        try:
            exporter = LangfuseExporter(public_key="pk", secret_key="sk",
                                        host=host, api_version="auto")
            self._run_real_agent(exporter)
            assert len(received["ingestion"]) == 1
            assert received["otel"] == []
            batch = received["ingestion"][0]["payload"]["batch"]
            types = [b["type"] for b in batch]
            assert types[0] == "trace-create"
            assert "span-create" in types
        finally:
            server.shutdown()

    def test_unreachable_server_never_breaks_the_run(self) -> None:
        exporter = LangfuseExporter(public_key="pk", secret_key="sk",
                                    host="http://127.0.0.1:9",  # nothing there
                                    api_version="auto",
                                    timeout_seconds=0.3)
        result = self._run_real_agent(exporter)
        assert result.output == "The sum is 5."   # agent unaffected
