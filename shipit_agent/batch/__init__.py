"""Batch API runtime for bulk / offline agent runs (~50% cost).

Wraps the Anthropic Messages Batches API for asynchronous, latency-tolerant
processing of many message requests at roughly half the standard per-token
price.

Example::

    from shipit_agent.batch import BatchRequest, BatchRuntime

    runtime = BatchRuntime(api_key="sk-...")
    results = runtime.run([
        BatchRequest(custom_id="q1", prompt="Summarise: ..."),
        BatchRequest(custom_id="q2", prompt="Classify: ..."),
    ])
"""

from __future__ import annotations

from .batch_runtime import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    BatchRequest,
    BatchResult,
    BatchRuntime,
    MessageBatchRunner,
)

__all__ = [
    "BatchRequest",
    "BatchResult",
    "BatchRuntime",
    "MessageBatchRunner",
    "DEFAULT_MODEL",
    "DEFAULT_MAX_TOKENS",
]
