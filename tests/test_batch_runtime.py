"""Tests for the Batch API runtime (shipit_agent.batch).

No network: a fake anthropic client mirrors exactly the attribute access the
runtime performs (``messages.batches.create/retrieve/results``), and polling
uses an injected no-op sleep.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shipit_agent.batch import BatchRequest, BatchResult, BatchRuntime


# --------------------------------------------------------------------------
# Fake anthropic client
# --------------------------------------------------------------------------


class _FakeBatch:
    """Mimics ``MessageBatch`` (only the fields the runtime reads)."""

    def __init__(self, batch_id: str, status: str) -> None:
        self.id = batch_id
        self.processing_status = status


class _FakeBatches:
    def __init__(self, *, statuses, results, batch_id="batch_123"):
        # statuses: list of processing_status values returned successively
        self._statuses = list(statuses)
        self._results = results
        self._batch_id = batch_id
        self.created_with = None  # captures the create() kwargs for assertions
        self.retrieve_calls = 0

    def create(self, *, requests):
        self.created_with = requests
        return _FakeBatch(self._batch_id, self._statuses[0])

    def retrieve(self, batch_id):
        self.retrieve_calls += 1
        # Advance through the status timeline, holding on the last value.
        idx = min(self.retrieve_calls, len(self._statuses) - 1)
        return _FakeBatch(batch_id, self._statuses[idx])

    def results(self, batch_id):
        # Real SDK returns a JSONLDecoder (iterable); a list iterates the same.
        return list(self._results)


class _FakeClient:
    def __init__(self, batches: _FakeBatches) -> None:
        self.messages = SimpleNamespace(batches=batches)


# --------------------------------------------------------------------------
# Result-entry builders (mirror the SDK's discriminated result objects)
# --------------------------------------------------------------------------


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _succeeded_entry(custom_id, text, usage=None):
    message = SimpleNamespace(
        content=[_text_block(text)],
        usage=usage or SimpleNamespace(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    result = SimpleNamespace(type="succeeded", message=message)
    return SimpleNamespace(custom_id=custom_id, result=result)


def _errored_entry(custom_id, message):
    error = SimpleNamespace(
        type="error",
        error=SimpleNamespace(type="invalid_request_error", message=message),
        request_id="req_1",
    )
    result = SimpleNamespace(type="errored", error=error)
    return SimpleNamespace(custom_id=custom_id, result=result)


def _canceled_entry(custom_id):
    result = SimpleNamespace(type="canceled")
    return SimpleNamespace(custom_id=custom_id, result=result)


# --------------------------------------------------------------------------
# submit()
# --------------------------------------------------------------------------


def test_submit_builds_payload_and_returns_id():
    batches = _FakeBatches(statuses=["in_progress"], results=[])
    runtime = BatchRuntime(_FakeClient(batches))

    batch_id = runtime.submit(
        [
            BatchRequest(
                custom_id="q1",
                prompt="Hello",
                system="Be brief.",
                model="claude-3-5-haiku-latest",
                max_tokens=256,
            )
        ]
    )

    assert batch_id == "batch_123"
    assert batches.created_with == [
        {
            "custom_id": "q1",
            "params": {
                "model": "claude-3-5-haiku-latest",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "Hello"}],
                "system": "Be brief.",
            },
        }
    ]


def test_submit_omits_system_when_absent_and_uses_defaults():
    batches = _FakeBatches(statuses=["in_progress"], results=[])
    runtime = BatchRuntime(
        _FakeClient(batches),
        default_model="default-model",
        default_max_tokens=1234,
    )

    runtime.submit([BatchRequest(custom_id="q2", prompt="Hi")])

    (entry,) = batches.created_with
    params = entry["params"]
    assert "system" not in params  # not emitted as None
    assert params["model"] == "default-model"
    assert params["max_tokens"] == 1234
    assert params["messages"] == [{"role": "user", "content": "Hi"}]


def test_submit_requires_requests():
    runtime = BatchRuntime(_FakeClient(_FakeBatches(statuses=["ended"], results=[])))
    with pytest.raises(ValueError):
        runtime.submit([])


def test_request_requires_prompt_or_messages():
    runtime = BatchRuntime(_FakeClient(_FakeBatches(statuses=["ended"], results=[])))
    with pytest.raises(ValueError):
        runtime.submit([BatchRequest(custom_id="bad")])


# --------------------------------------------------------------------------
# run() — polling + result mapping
# --------------------------------------------------------------------------


def test_run_polls_until_ended_and_maps_results():
    sleeps: list[float] = []
    # in_progress -> in_progress -> ended (terminal). 'canceling' is transient.
    batches = _FakeBatches(
        statuses=["in_progress", "in_progress", "canceling", "ended"],
        results=[
            _succeeded_entry("q1", "Hello world"),
            _errored_entry("q2", "rate limited"),
        ],
    )
    runtime = BatchRuntime(_FakeClient(batches))

    results = runtime.run(
        [
            BatchRequest(custom_id="q1", prompt="a"),
            BatchRequest(custom_id="q2", prompt="b"),
        ],
        poll_interval=7.0,
        sleep=sleeps.append,  # no-op, records the intervals
    )

    # Polled multiple times before reaching 'ended'.
    assert batches.retrieve_calls >= 2
    assert all(s == 7.0 for s in sleeps)

    by_id = {r.custom_id: r for r in results}

    ok = by_id["q1"]
    assert isinstance(ok, BatchResult)
    assert ok.ok is True
    assert ok.output == "Hello world"
    assert ok.usage.output_tokens == 5
    assert ok.error is None
    assert ok.result_type == "succeeded"

    err = by_id["q2"]
    assert err.ok is False
    assert err.error == "rate limited"
    assert err.output == ""
    assert err.result_type == "errored"


def test_run_with_immediate_ended_does_not_sleep():
    sleeps: list[float] = []
    batches = _FakeBatches(
        statuses=["ended"],
        results=[_succeeded_entry("q1", "done")],
    )
    runtime = BatchRuntime(_FakeClient(batches))

    results = runtime.run(
        [BatchRequest(custom_id="q1", prompt="x")],
        sleep=sleeps.append,
    )

    assert sleeps == []  # already terminal on first poll
    assert results[0].output == "done"


def test_canceled_result_is_captured_as_error():
    batches = _FakeBatches(
        statuses=["ended"],
        results=[_canceled_entry("q3")],
    )
    runtime = BatchRuntime(_FakeClient(batches))
    results = runtime.run(
        [BatchRequest(custom_id="q3", prompt="x")],
        sleep=lambda _i: None,
    )
    assert results[0].error == "Request canceled"
    assert results[0].result_type == "canceled"
    assert results[0].ok is False


def test_mapping_failure_is_captured_not_raised():
    # Entry whose .result attribute access blows up -> captured as error.
    bad_entry = SimpleNamespace(custom_id="q4")  # no .result attribute
    batches = _FakeBatches(statuses=["ended"], results=[bad_entry])
    runtime = BatchRuntime(_FakeClient(batches))

    results = runtime.results("batch_123")

    assert len(results) == 1
    assert results[0].custom_id == "q4"
    assert results[0].error is not None
    assert "Failed to map batch result" in results[0].error


def test_run_times_out_with_injected_clock():
    clock = {"t": 0.0}

    def fake_now():
        return clock["t"]

    def fake_sleep(interval):
        clock["t"] += interval  # advance the injected clock

    batches = _FakeBatches(statuses=["in_progress"], results=[])  # never ends
    runtime = BatchRuntime(_FakeClient(batches))

    with pytest.raises(TimeoutError):
        runtime.run(
            [BatchRequest(custom_id="q1", prompt="x")],
            poll_interval=10.0,
            timeout=25.0,
            sleep=fake_sleep,
            now=fake_now,
        )
