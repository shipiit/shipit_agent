"""RedactingTraceStore scrubs secrets (and PII when asked) before any exporter sees an event."""

from __future__ import annotations

from typing import Any

import pytest

from shipit_agent.core.models import AgentEvent
from shipit_agent.observability.tracing import InMemoryTraceStore
from shipit_agent.tracing_exporters import RedactingTraceStore

KEY = "sk-" + "a" * 32
GITHUB = "ghp_" + "b" * 36


def _sent(store: RedactingTraceStore, inner: InMemoryTraceStore) -> AgentEvent:
    record = inner.load("t")
    assert record is not None
    return record.events[-1]


def test_secrets_are_scrubbed_everywhere_in_the_event() -> None:
    inner = InMemoryTraceStore()
    store = RedactingTraceStore(inner)
    event = AgentEvent(
        type="tool_completed",
        message=f"used {KEY}",
        payload={"output": f"token {GITHUB}", "nested": [{"deep": KEY}, 7, None], "count": 3},
    )
    store.append_event("t", event, {"note": KEY})
    sent = _sent(store, inner)
    text = repr((sent.message, sent.payload, inner.load("t").metadata))
    assert KEY not in text and GITHUB not in text
    assert "[REDACTED:api-key]" in sent.message
    assert sent.payload["count"] == 3 and sent.payload["nested"][1:] == [7, None]
    # The caller's event is not changed: the run's own record stays exact.
    assert event.message == f"used {KEY}" and event.payload["nested"][0]["deep"] == KEY


@pytest.mark.parametrize("key", ["api_key", "Authorization", "password", "x-api-key", "access_token", "secret"])
def test_values_under_credential_keys_are_hidden(key: str) -> None:
    inner = InMemoryTraceStore()
    RedactingTraceStore(inner).append_event("t", AgentEvent(type="tool_called", payload={"arguments": {key: "hunter2"}}))
    assert inner.load("t").events[-1].payload["arguments"][key] == "[REDACTED]"


def test_pii_is_kept_unless_asked_for() -> None:
    event = AgentEvent(type="run_completed", message="mail a@b.co")
    plain, strict = InMemoryTraceStore(), InMemoryTraceStore()
    RedactingTraceStore(plain).append_event("t", event)
    RedactingTraceStore(strict, pii=True).append_event("t", event)
    assert plain.load("t").events[-1].message == "mail a@b.co"
    assert strict.load("t").events[-1].message == "mail [REDACTED:email]"


def test_a_custom_redactor_runs_after_the_patterns() -> None:
    inner = InMemoryTraceStore()
    RedactingTraceStore(inner, redact=lambda text: text.replace("ACME", "[client]")).append_event(
        "t", AgentEvent(type="run_completed", message=f"ACME {KEY}")
    )
    assert inner.load("t").events[-1].message == "[client] [REDACTED:api-key]"


@pytest.mark.parametrize("payload", [{}, {"empty": ""}, {"n": 0}, {"long": "x" * 100_000}])
def test_edge_payloads_pass_through(payload: dict[str, Any]) -> None:
    inner = InMemoryTraceStore()
    RedactingTraceStore(inner).append_event("t", AgentEvent(type="run_started", payload=payload))
    assert inner.load("t").events[-1].payload == payload


def test_load_reads_from_the_wrapped_store() -> None:
    inner = InMemoryTraceStore()
    store = RedactingTraceStore(inner)
    assert store.load("missing") is None
    store.append_event("t", AgentEvent(type="run_started"))
    assert store.load("t") is inner.load("t")


def test_token_counts_are_not_mistaken_for_tokens() -> None:
    inner = InMemoryTraceStore()
    usage = {"input_tokens": 120, "max_tokens": 4096, "cache_read_input_tokens": 0}
    RedactingTraceStore(inner).append_event("t", AgentEvent(type="llm_completed", payload={"usage": usage}))
    assert inner.load("t").events[-1].payload["usage"] == usage


def test_ids_survive_pii_redaction() -> None:
    """A UUID's digits must not be read as a phone number: ids are how traces are joined."""
    run_id = "fd6792f8-033f-41f3-a182-4455667f7453"
    inner = InMemoryTraceStore()
    event = AgentEvent(type="run_started", message=f"run {run_id} for +44 20 7946 0958",
                       payload={"run_id": run_id, "session_id": run_id.upper(), "note": f"see {run_id}, call 415-555-0132"})
    RedactingTraceStore(inner, pii=True).append_event("t", event, {"trace_id": run_id})
    sent = inner.load("t").events[-1]
    assert sent.payload["run_id"] == run_id and sent.payload["session_id"] == run_id.upper()
    assert inner.load("t").metadata["trace_id"] == run_id
    assert run_id in sent.message and run_id in sent.payload["note"]
    assert "7946" not in sent.message and "555-0132" not in sent.payload["note"]
