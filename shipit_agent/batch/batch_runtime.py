"""Batch API runtime for shipit-agent.

Wraps the Anthropic *Messages Batches* API for bulk / offline agent runs.
The Batches API processes many message requests asynchronously and is billed
at roughly **50% of the standard per-token price**, which makes it ideal for
large, latency-tolerant workloads (evals, backfills, nightly summarisation,
dataset labelling, etc.).

SDK surface used (anthropic >= 0.79):

* ``client.messages.batches.create(requests=[{"custom_id": ..., "params": {...}}])``
  -> ``MessageBatch`` (``.id``, ``.processing_status``)
* ``client.messages.batches.retrieve(batch_id)`` -> ``MessageBatch``
* ``client.messages.batches.results(batch_id)`` -> iterable of
  ``MessageBatchIndividualResponse`` (``.custom_id``, ``.result``)
* ``client.messages.batches.cancel(batch_id)`` -> ``MessageBatch``

``processing_status`` is one of ``"in_progress" | "canceling" | "ended"``;
only ``"ended"`` is terminal.

Each individual ``result`` is discriminated by ``result.type``:
``"succeeded"`` (has ``.message``), ``"errored"`` (has ``.error``),
``"canceled"``, or ``"expired"``.

Example::

    from shipit_agent.batch import BatchRequest, BatchRuntime

    runtime = BatchRuntime(api_key="sk-...")
    results = runtime.run([
        BatchRequest(custom_id="q1", prompt="Summarise this ticket: ..."),
        BatchRequest(custom_id="q2", prompt="Classify sentiment: ..."),
    ])
    for r in results:
        print(r.custom_id, r.output if not r.error else f"ERROR: {r.error}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional

__all__ = [
    "BatchRequest",
    "BatchResult",
    "BatchRuntime",
    "MessageBatchRunner",
    "DEFAULT_MODEL",
    "DEFAULT_MAX_TOKENS",
]

# Sensible defaults used when a :class:`BatchRequest` does not specify its own.
DEFAULT_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_MAX_TOKENS = 1024

# Terminal value of ``MessageBatch.processing_status``.
_TERMINAL_STATUS = "ended"


@dataclass
class BatchRequest:
    """A single request to include in a message batch.

    Attributes:
        custom_id: Caller-provided identifier, echoed back on the matching
            :class:`BatchResult`. Must be unique within a batch.
        prompt: Convenience single-turn user prompt. Used to build a
            ``messages`` payload when ``messages`` is not supplied.
        messages: Explicit list of message dicts (``{"role", "content"}``).
            Takes precedence over ``prompt`` when both are given.
        system: Optional system prompt. Omitted from the payload when ``None``.
        max_tokens: Max output tokens for this request.
        model: Model id for this request.
        metadata: Optional ``metadata`` object forwarded to the API.
    """

    custom_id: str
    prompt: Optional[str] = None
    messages: Optional[List[dict]] = None
    system: Optional[str] = None
    max_tokens: Optional[int] = None
    model: Optional[str] = None
    metadata: Optional[dict] = None

    def to_params(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Build the ``params`` block for the Batches ``create`` payload.

        Keys are emitted to match the Messages API ``create`` shape. Optional
        keys (``system``, ``metadata``) are only included when set, so the
        resulting dict mirrors exactly what the SDK expects.
        """
        if self.messages is not None:
            messages = self.messages
        elif self.prompt is not None:
            messages = [{"role": "user", "content": self.prompt}]
        else:
            raise ValueError(
                f"BatchRequest {self.custom_id!r} must set either 'prompt' or 'messages'"
            )

        params: dict[str, Any] = {
            "model": self.model or default_model,
            "max_tokens": self.max_tokens or default_max_tokens,
            "messages": messages,
        }
        if self.system is not None:
            params["system"] = self.system
        if self.metadata is not None:
            params["metadata"] = self.metadata
        return params

    def to_payload(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Build the full ``{"custom_id", "params"}`` entry for ``create``."""
        return {
            "custom_id": self.custom_id,
            "params": self.to_params(
                default_model=default_model,
                default_max_tokens=default_max_tokens,
            ),
        }


@dataclass
class BatchResult:
    """The outcome of a single batched request.

    Attributes:
        custom_id: The ``custom_id`` of the originating :class:`BatchRequest`.
        output: Concatenated assistant text on success, otherwise ``""``.
        usage: The message ``usage`` object on success, otherwise ``None``.
        error: Human-readable error string for ``errored`` / ``canceled`` /
            ``expired`` results (or a mapping failure), otherwise ``None``.
        result_type: Raw discriminator: ``succeeded`` / ``errored`` /
            ``canceled`` / ``expired``.
        raw: The underlying SDK result object, for callers that need full
            access (stop reason, content blocks, request id, ...).
    """

    custom_id: str
    output: str = ""
    usage: Any = None
    error: Optional[str] = None
    result_type: Optional[str] = None
    raw: Any = None

    @property
    def ok(self) -> bool:
        """True when the request succeeded (no error captured)."""
        return self.error is None and self.result_type == "succeeded"


def _extract_text(message: Any) -> str:
    """Concatenate the text of all ``text`` content blocks in a message."""
    parts: List[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


class BatchRuntime:
    """Runner for the Anthropic Messages Batches API.

    Cost note: batched requests are billed at ~50% of standard per-token
    pricing, in exchange for asynchronous (up to 24h) processing.

    Args:
        client: A pre-built anthropic client (or any object exposing
            ``messages.batches.create/retrieve/results/cancel``). Injectable
            for testing. When ``None``, a real ``anthropic.Anthropic`` client
            is constructed from ``api_key``.
        api_key: API key used only when ``client`` is not provided.
        default_model: Fallback model for requests without an explicit model.
        default_max_tokens: Fallback ``max_tokens`` for requests without one.
    """

    def __init__(
        self,
        client: Any = None,
        *,
        api_key: Optional[str] = None,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if client is None:
            import anthropic  # imported lazily so tests need no real client

            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens

    # -- core operations ---------------------------------------------------

    def submit(self, requests: Iterable[BatchRequest]) -> str:
        """Submit a batch and return its id.

        Builds the ``requests=[{"custom_id", "params"}]`` payload and calls
        ``client.messages.batches.create(...)``.
        """
        payload = [
            req.to_payload(
                default_model=self.default_model,
                default_max_tokens=self.default_max_tokens,
            )
            for req in requests
        ]
        if not payload:
            raise ValueError("submit() requires at least one BatchRequest")
        batch = self.client.messages.batches.create(requests=payload)
        return batch.id

    def status(self, batch_id: str) -> str:
        """Return the batch ``processing_status``.

        One of ``"in_progress" | "canceling" | "ended"``.
        """
        batch = self.client.messages.batches.retrieve(batch_id)
        return batch.processing_status

    def cancel(self, batch_id: str) -> str:
        """Request cancellation of an in-progress batch; returns new status."""
        batch = self.client.messages.batches.cancel(batch_id)
        return batch.processing_status

    def results(self, batch_id: str) -> List[BatchResult]:
        """Stream and map the batch results into :class:`BatchResult` objects.

        Every per-entry mapping is wrapped so a malformed entry becomes a
        ``BatchResult`` with ``error`` set rather than raising.
        """
        mapped: List[BatchResult] = []
        for entry in self.client.messages.batches.results(batch_id):
            mapped.append(self._map_entry(entry))
        return mapped

    def run(
        self,
        requests: Iterable[BatchRequest],
        *,
        poll_interval: float = 30.0,
        timeout: float = 24 * 60 * 60,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> List[BatchResult]:
        """Submit, poll until the batch ends, and return mapped results.

        Args:
            requests: The batch requests to run.
            poll_interval: Seconds between status polls.
            timeout: Max seconds to wait for the batch to end.
            sleep: Sleep callable (injectable; pass a no-op in tests).
            now: Monotonic clock callable (injectable for deterministic
                timeout testing).

        Raises:
            TimeoutError: If the batch does not reach ``"ended"`` in time.
        """
        batch_id = self.submit(requests)
        start = now()
        while True:
            if self.status(batch_id) == _TERMINAL_STATUS:
                break
            if now() - start >= timeout:
                raise TimeoutError(
                    f"Batch {batch_id} did not end within {timeout}s"
                )
            sleep(poll_interval)
        return self.results(batch_id)

    # -- internals ---------------------------------------------------------

    def _map_entry(self, entry: Any) -> BatchResult:
        """Map one ``MessageBatchIndividualResponse`` into a BatchResult."""
        custom_id = getattr(entry, "custom_id", None) or ""
        try:
            result = entry.result
            rtype = getattr(result, "type", None)

            if rtype == "succeeded":
                message = result.message
                return BatchResult(
                    custom_id=custom_id,
                    output=_extract_text(message),
                    usage=getattr(message, "usage", None),
                    result_type="succeeded",
                    raw=result,
                )

            if rtype == "errored":
                return BatchResult(
                    custom_id=custom_id,
                    error=_error_message(result.error),
                    result_type="errored",
                    raw=result,
                )

            if rtype in ("canceled", "expired"):
                return BatchResult(
                    custom_id=custom_id,
                    error=f"Request {rtype}",
                    result_type=rtype,
                    raw=result,
                )

            return BatchResult(
                custom_id=custom_id,
                error=f"Unknown result type: {rtype!r}",
                result_type=rtype,
                raw=result,
            )
        except Exception as exc:  # mapping must capture, never raise
            return BatchResult(
                custom_id=custom_id,
                error=f"Failed to map batch result: {exc}",
                raw=entry,
            )


def _error_message(error: Any) -> str:
    """Best-effort extraction of a readable message from an error response."""
    inner = getattr(error, "error", error)
    message = getattr(inner, "message", None)
    if message:
        return str(message)
    return str(error)


# Backwards/alternate-name alias requested by the spec.
MessageBatchRunner = BatchRuntime
