from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.tracing_exporters import (
    LangSmithExporter,
    OpenTelemetryExporter,
)
from shipit_agent.tracing_exporters import langsmith_exporter as lse_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []
        self.raises: Exception | None = None

    def __call__(self, req: urllib.request.Request, timeout: float = 5.0) -> _FakeResponse:
        self.requests.append(req)
        if self.raises is not None:
            raise self.raises
        return _FakeResponse()


class _FakeSpan:
    def __init__(self, name: str, attributes: dict[str, Any] | None) -> None:
        self.name = name
        self.attributes = dict(attributes or {})
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.ended = False

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((name, dict(attributes or {})))

    def end(self) -> None:
        self.ended = True


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def start_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> _FakeSpan:
        span = _FakeSpan(name, attributes)
        self.spans.append(span)
        return span


class _FakeTracerProvider:
    def __init__(self) -> None:
        self.tracer = _FakeTracer()
        self.requested_names: list[str] = []

    def get_tracer(self, name: str) -> _FakeTracer:
        self.requested_names.append(name)
        return self.tracer


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _event(type_: str = "run_started", message: str = "hi", **payload: Any) -> AgentEvent:
    return AgentEvent(type=type_, message=message, payload=dict(payload))


# ---------------------------------------------------------------------------
# LangSmithExporter
# ---------------------------------------------------------------------------


def test_langsmith_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGCHAIN_API_KEY", "env-key")
    exporter = LangSmithExporter()
    assert exporter.api_key == "env-key"


def test_langsmith_constructor_api_key_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGCHAIN_API_KEY", "env-key")
    exporter = LangSmithExporter(api_key="explicit")
    assert exporter.api_key == "explicit"


def test_langsmith_without_api_key_logs_warning_and_does_not_post(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)

    exporter = LangSmithExporter(batch_size=1)
    with caplog.at_level("WARNING"):
        exporter.append_event("t-1", _event())

    assert recorder.requests == []
    assert any("no API key" in rec.message for rec in caplog.records)


def test_langsmith_happy_path_builds_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)

    exporter = LangSmithExporter(api_key="secret", batch_size=1, project="proj-x")
    exporter.append_event(
        "trace-42",
        _event("run_started", "hello", step=1),
        metadata={"user": "rahul"},
    )

    assert len(recorder.requests) == 1
    req = recorder.requests[0]
    assert req.full_url == "https://api.smith.langchain.com/runs"
    assert req.get_method() == "POST"
    assert req.headers.get("X-api-key") == "secret"
    assert req.headers.get("Content-type") == "application/json"

    body = json.loads(req.data.decode("utf-8"))
    assert "runs" in body and len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["name"] == "run_started"
    assert run["run_type"] == "chain"
    assert run["inputs"] == {"message": "hello"}
    assert run["outputs"] == {"step": 1}
    assert run["start_time"] and run["end_time"]
    assert run["extra"]["trace_id"] == "trace-42"
    assert run["extra"]["project"] == "proj-x"
    assert run["extra"]["metadata"] == {"user": "rahul"}


def test_langsmith_batch_flushes_at_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)
    clock = _Clock()

    exporter = LangSmithExporter(
        api_key="k",
        batch_size=20,
        flush_interval_seconds=1000.0,
        time_source=clock,
    )
    for i in range(19):
        exporter.append_event("t", _event(step=i))
    assert recorder.requests == []  # still buffering
    exporter.append_event("t", _event(step=19))

    assert len(recorder.requests) == 1
    body = json.loads(recorder.requests[0].data.decode("utf-8"))
    assert len(body["runs"]) == 20


def test_langsmith_batch_flushes_on_time_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)
    clock = _Clock()

    exporter = LangSmithExporter(
        api_key="k",
        batch_size=20,
        flush_interval_seconds=2.0,
        time_source=clock,
    )
    for i in range(5):
        exporter.append_event("t", _event(step=i))
    assert recorder.requests == []

    # Advance past the flush interval; next append triggers the time-based flush.
    clock.advance(2.5)
    exporter.append_event("t", _event(step=5))

    assert len(recorder.requests) == 1
    body = json.loads(recorder.requests[0].data.decode("utf-8"))
    # 5 buffered + the 6th that triggered the flush
    assert len(body["runs"]) == 6


def test_langsmith_transport_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = _Recorder()
    recorder.raises = urllib.error.URLError("boom")
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)

    exporter = LangSmithExporter(api_key="k", batch_size=1)
    with caplog.at_level("WARNING"):
        # Must not raise.
        exporter.append_event("t", _event())

    assert len(recorder.requests) == 1
    assert any("failed to post" in rec.message for rec in caplog.records)


def test_langsmith_flush_is_noop_when_buffer_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)

    exporter = LangSmithExporter(api_key="k")
    exporter.flush()
    assert recorder.requests == []


def test_langsmith_load_returns_none() -> None:
    exporter = LangSmithExporter(api_key="k")
    assert exporter.load("anything") is None


# ---------------------------------------------------------------------------
# OpenTelemetryExporter
# ---------------------------------------------------------------------------


pytest.importorskip("opentelemetry")


def test_otel_missing_package_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="opentelemetry-api"):
        OpenTelemetryExporter()


def test_otel_happy_path_starts_span_with_attributes() -> None:
    provider = _FakeTracerProvider()
    exporter = OpenTelemetryExporter(
        service_name="svc-a", tracer_provider=provider
    )

    exporter.append_event(
        "trace-1",
        _event("run_started", "hello", step=1, detail="x"),
        metadata={"user": "rahul"},
    )

    assert provider.requested_names == ["svc-a"]
    assert len(provider.tracer.spans) == 1
    span = provider.tracer.spans[0]
    assert span.name == "agent.run_started"
    assert span.attributes["shipit.trace_id"] == "trace-1"
    assert span.attributes["shipit.event.type"] == "run_started"
    assert span.attributes["shipit.event.message"] == "hello"
    assert span.attributes["shipit.payload.step"] == 1
    assert span.attributes["shipit.payload.detail"] == "x"
    assert span.attributes["shipit.metadata.user"] == "rahul"


def test_otel_span_is_ended_after_append() -> None:
    provider = _FakeTracerProvider()
    exporter = OpenTelemetryExporter(tracer_provider=provider)
    exporter.append_event("t", _event())
    assert provider.tracer.spans[0].ended is True


def test_otel_payload_events_become_span_events() -> None:
    provider = _FakeTracerProvider()
    exporter = OpenTelemetryExporter(tracer_provider=provider)
    exporter.append_event(
        "t",
        _event(
            "run_completed",
            "done",
            events=[
                {"name": "tool_call", "tool": "search", "status": "ok"},
                {"name": "llm_reply", "tokens": 42},
            ],
        ),
    )
    span = provider.tracer.spans[0]
    assert [e[0] for e in span.events] == ["tool_call", "llm_reply"]
    assert span.events[0][1]["shipit.event.tool"] == "search"
    assert span.events[0][1]["shipit.event.status"] == "ok"
    assert span.events[1][1]["shipit.event.tokens"] == 42
    # The "events" list should not also leak into span attributes.
    assert "shipit.payload.events" not in span.attributes


def test_otel_load_returns_none() -> None:
    provider = _FakeTracerProvider()
    exporter = OpenTelemetryExporter(tracer_provider=provider)
    assert exporter.load("anything") is None


# ---------------------------------------------------------------------------
# Protocol adherence
# ---------------------------------------------------------------------------


def test_both_exporters_adhere_to_trace_store_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(lse_module.urllib.request, "urlopen", recorder)

    provider = _FakeTracerProvider()
    langsmith = LangSmithExporter(api_key="k", batch_size=1)
    otel = OpenTelemetryExporter(tracer_provider=provider)

    for exporter in (langsmith, otel):
        # Structural compatibility with the TraceStore Protocol.
        assert callable(getattr(exporter, "append_event", None))
        assert callable(getattr(exporter, "load", None))
        # Signature adherence: same call shape as InMemoryTraceStore.
        exporter.append_event("trace-x", _event(), metadata={"k": "v"})
        assert exporter.load("trace-x") is None
